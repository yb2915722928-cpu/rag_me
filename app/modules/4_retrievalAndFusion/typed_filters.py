"""Validated filters shared by SQL retrieval and in-memory candidate reads.

Metadata fields are top-level JSON keys. Datetimes must include a timezone;
sets are JSON arrays of one declared scalar kind. Ordinary comparisons never
match absent/null values. `exists` includes explicit null, `is_null` does not
include absence. `range` is lower-inclusive / upper-exclusive by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from types import MappingProxyType
from typing import Mapping


from .contracts import RetrievalContractError


class FilterValidationError(RetrievalContractError):
    """A filter cannot be implemented without changing its meaning."""


SCALARS = frozenset({"string", "number", "boolean", "datetime"})
KINDS = SCALARS | {f"set[{kind}]" for kind in SCALARS}


def validate_field_types(fields: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(fields, Mapping):
        raise FilterValidationError("field declarations must be a mapping")
    result = dict(fields)
    for name, kind in result.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(kind, str) or kind not in KINDS:
            raise FilterValidationError("unsupported filter field declaration")
    return result


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FilterValidationError("invalid datetime") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FilterValidationError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


def _value(value, kind, now=None):
    if kind == "datetime":
        if isinstance(value, Mapping) and set(value) == {"now"} and value["now"] is True:
            if now is None:
                raise FilterValidationError("now is only valid in query conditions")
            return now
        return _time(value)
    if kind.startswith("set["):
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise FilterValidationError("set field requires a collection")
        return frozenset(_value(item, kind[4:-1], now) for item in value)
    valid = ((kind == "string" and isinstance(value, str))
             or (kind == "boolean" and type(value) is bool)
             or (kind == "number" and (type(value) is int or (type(value) is float and math.isfinite(value)))))
    if not valid:
        raise FilterValidationError("filter value does not match the declared field type")
    return value


def validate_metadata(metadata, field_types):
    for field, kind in validate_field_types(field_types).items():
        if field in metadata and metadata[field] is not None:
            _value(metadata[field], kind)


@dataclass(frozen=True)
class _Node:
    op: str
    field: str = ""
    kind: str = ""
    value: object = None
    children: tuple = ()
    lower: object = None
    upper: object = None
    include_lower: bool = True
    include_upper: bool = False


def _parse(expression, fields, now, depth=0):
    if depth > 64:
        raise FilterValidationError("filter nesting exceeds 64")
    if not isinstance(expression, Mapping):
        raise FilterValidationError("filter expression must be a mapping")
    if set(expression) & {"and", "or"}:
        if len(expression) != 1:
            raise FilterValidationError("boolean group cannot contain other keys")
        op, children = next(iter(expression.items()))
        if not isinstance(children, (tuple, list)) or not children:
            raise FilterValidationError("boolean group requires nonempty children")
        return _Node(op, children=tuple(_parse(child, fields, now, depth + 1) for child in children))
    field, op = expression.get("field"), expression.get("op")
    if not isinstance(field, str) or field not in fields:
        raise FilterValidationError("unknown filter field")
    if not isinstance(op, str):
        raise FilterValidationError("filter operation must be a string")
    kind = fields[field]
    allowed = {"field", "op"}
    if op in {"exists", "missing", "is_null"}:
        node = _Node(op, field, kind)
    elif op in {"eq", "in", "contains", "lt", "lte", "gt", "gte"}:
        allowed.add("value")
        if "value" not in expression:
            raise FilterValidationError("comparison requires value")
        value = expression["value"]
        if op == "in":
            if kind not in SCALARS or not isinstance(value, (list, tuple)):
                raise FilterValidationError("IN requires a scalar field and list")
            value = tuple(_value(item, kind, now) for item in value)
        elif op == "contains":
            if not kind.startswith("set["):
                raise FilterValidationError("contains requires a set field")
            value = _value(value, kind[4:-1], now)
        else:
            if op != "eq" and kind not in {"number", "datetime"}:
                raise FilterValidationError("ordered comparison requires number or datetime")
            value = _value(value, kind, now)
        node = _Node(op, field, kind, value)
    elif op == "range":
        allowed |= {"lower", "upper", "include_lower", "include_upper"}
        if kind not in {"number", "datetime"} or not set(expression) & {"lower", "upper"}:
            raise FilterValidationError("range requires number/datetime and a bound")
        lower = _value(expression["lower"], kind, now) if "lower" in expression else None
        upper = _value(expression["upper"], kind, now) if "upper" in expression else None
        il, iu = expression.get("include_lower", True), expression.get("include_upper", False)
        if type(il) is not bool or type(iu) is not bool or (lower is not None and upper is not None and lower > upper):
            raise FilterValidationError("invalid range bounds")
        node = _Node(op, field, kind, lower=lower, upper=upper, include_lower=il, include_upper=iu)
    else:
        raise FilterValidationError("unsupported filter operation")
    if set(expression) - allowed:
        raise FilterValidationError("unknown filter expression keys")
    return node


def _matches(node, metadata):
    if node.op == "true":
        return True
    if node.op in {"and", "or"}:
        values = (_matches(child, metadata) for child in node.children)
        return all(values) if node.op == "and" else any(values)
    present = node.field in metadata
    value = metadata.get(node.field)
    if node.op == "exists":
        return present
    if node.op == "missing":
        return not present
    if node.op == "is_null":
        return present and value is None
    if not present or value is None:
        return False
    value = _value(value, node.kind)
    if node.op == "eq":
        return value == node.value
    if node.op == "in":
        return value in node.value
    if node.op == "contains":
        return node.value in value
    if node.op == "range":
        return ((node.lower is None or (value >= node.lower if node.include_lower else value > node.lower))
                and (node.upper is None or (value <= node.upper if node.include_upper else value < node.upper)))
    if node.op == "lt":
        return value < node.value
    if node.op == "lte":
        return value <= node.value
    if node.op == "gt":
        return value > node.value
    return value >= node.value


def _sql(node, column):
    if node.op == "true":
        return "TRUE", []
    if node.op in {"and", "or"}:
        children = [_sql(child, column) for child in node.children]
        return "(" + (" AND " if node.op == "and" else " OR ").join(s for s, _ in children) + ")", [p for _, ps in children for p in ps]
    if node.op == "exists":
        return f"({column} ? %s)", [node.field]
    if node.op == "missing":
        return f"(NOT ({column} ? %s))", [node.field]
    if node.op == "is_null":
        return f"(({column} -> %s) = 'null'::jsonb)", [node.field]
    # Typed casts use metadata validated at snapshot preparation. Corrupt values
    # fail the entire path instead of silently weakening the requested filter.
    cast = {"string": "text", "number": "numeric", "boolean": "boolean", "datetime": "timestamptz"}
    def scalar_sql(kind):
        return f"(({column} ->> %s)::{cast[kind]})"
    if node.op == "in":
        if not node.value:
            return "FALSE", []
        comparisons = [f"{scalar_sql(node.kind)} = %s" for _ in node.value]
        params = [p for value in node.value for p in (node.field, value)]
        return "COALESCE((" + " OR ".join(comparisons) + "), FALSE)", params
    if node.op == "contains" or node.kind.startswith("set["):
        kind = node.kind[4:-1]
        values = node.value if node.op == "eq" else (node.value,)
        # Compare canonical typed element sets; datetime strings can use distinct
        # timezone offsets and still denote the same member.
        element = f"(e.value #>> '{{}}')::{cast[kind]}"
        array = (f"ARRAY(SELECT DISTINCT {element} FROM jsonb_array_elements("
                 f"COALESCE(NULLIF({column} -> %s, 'null'::jsonb), '[]'::jsonb)) e(value))")
        if node.op == "contains":
            return f"COALESCE((%s = ANY({array})), FALSE)", [node.value, node.field]
        return (f"COALESCE((({column} -> %s) IS NOT NULL AND ({column} -> %s) <> 'null'::jsonb "
                f"AND {array} @> %s::{cast[kind]}[] AND {array} <@ %s::{cast[kind]}[]), FALSE)",
                [node.field, node.field, node.field, list(values), node.field, list(values)])
    if node.op == "range":
        parts, params = [], []
        for bound, operator in ((node.lower, ">=" if node.include_lower else ">"),
                                (node.upper, "<=" if node.include_upper else "<")):
            if bound is not None:
                parts.append(f"{scalar_sql(node.kind)} {operator} %s")
                params.extend((node.field, bound))
        return "COALESCE((" + " AND ".join(parts) + "), FALSE)", params
    operator = {"eq": "=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[node.op]
    return f"COALESCE(({scalar_sql(node.kind)} {operator} %s), FALSE)", [node.field, node.value]


@dataclass(frozen=True)
class FilterPlan:
    root: _Node
    field_types: Mapping[str, str]
    now: datetime

    def matches(self, metadata: Mapping) -> bool:
        return _matches(self.root, metadata)

    def sql(self, column="c.metadata") -> tuple[str, list]:
        if not isinstance(column, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*(\.[a-zA-Z_][a-zA-Z_0-9]*)?", column):
            raise FilterValidationError("invalid metadata SQL column")
        return _sql(self.root, column)


def compile_filter(condition, field_types, *, now=None) -> FilterPlan:
    fields = validate_field_types(field_types)
    instant = _time(now if now is not None else datetime.now(timezone.utc))
    root = _Node("true") if condition is None else _parse(condition, fields, instant)
    return FilterPlan(root, MappingProxyType(fields), instant)
