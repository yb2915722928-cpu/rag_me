"""The deliberately small, fail-closed filter language available in #83.

#84 extends this module's expression, validation and SQL compiler together.
Only declared string/number/boolean equality and conjunction are available now.
"""
from dataclasses import dataclass
import math
from typing import Mapping

from app.models.embedding import canonical_json
from .contracts import RetrievalContractError


@dataclass(frozen=True)
class Eq:
    field: str
    value: str | int | float | bool


@dataclass(frozen=True)
class All:
    conditions: tuple

    def __post_init__(self):
        object.__setattr__(self, "conditions", tuple(self.conditions))


def validate_field_types(field_types: Mapping[str, str]) -> dict[str, str]:
    fields = dict(field_types)
    for name, kind in fields.items():
        if not isinstance(name, str) or not name.strip() or kind not in {"string", "number", "boolean"}:
            raise RetrievalContractError("unsupported filter field declaration")
    return fields


def validate_metadata(metadata, field_types):
    for name, kind in field_types.items():
        value = metadata.get(name)
        if value is not None:
            _validate_value(value, kind)


def validate_condition(condition, field_types):
    if condition is None:
        return
    if isinstance(condition, All):
        for child in condition.conditions:
            # None is only the root no-condition sentinel, never an expression.
            if child is None:
                raise RetrievalContractError("null is not a filter expression")
            validate_condition(child, field_types)
        return
    if not isinstance(condition, Eq):
        raise RetrievalContractError("unsupported filter operation")
    if not isinstance(condition.field, str) or condition.field not in field_types:
        raise RetrievalContractError("unknown filter field")
    _validate_value(condition.value, field_types[condition.field])


def _validate_value(value, kind):
    valid = ((kind == "string" and isinstance(value, str))
             or (kind == "boolean" and type(value) is bool)
             or (kind == "number" and type(value) in (int, float) and math.isfinite(value)))
    if not valid:
        raise RetrievalContractError("filter value does not match the declared field type")


def compile_condition(condition) -> tuple[str, list]:
    """Compile an already validated expression against content alias c.

    Field names and values are bound parameters, never SQL identifiers. JSONB
    equality preserves boolean/number distinctions; missing/null never match.
    """
    if condition is None:
        return "TRUE", []
    if isinstance(condition, All):
        compiled = [compile_condition(child) for child in condition.conditions]
        return ("(" + " AND ".join(sql for sql, _ in compiled) + ")" if compiled else "TRUE",
                [value for _, values in compiled for value in values])
    return "(c.metadata -> %s) = %s::jsonb", [condition.field, canonical_json(condition.value)]
