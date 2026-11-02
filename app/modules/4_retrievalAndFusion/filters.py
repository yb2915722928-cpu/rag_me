"""Compatibility constructors and the single typed condition entry boundary."""
from dataclasses import dataclass

from .typed_filters import (FilterPlan, FilterValidationError, compile_filter,
                            validate_field_types, validate_metadata)


@dataclass(frozen=True)
class Eq:
    field: str
    value: object


@dataclass(frozen=True)
class All:
    conditions: tuple

    def __post_init__(self):
        object.__setattr__(self, "conditions", tuple(self.conditions))


def _expression(condition):
    if isinstance(condition, Eq):
        return {"field": condition.field, "op": "eq", "value": condition.value}
    if isinstance(condition, All):
        if not condition.conditions:
            return None
        return {"and": [_expression(child) for child in condition.conditions]}
    return condition


def validate_condition(condition, field_types, *, now=None):
    return compile_filter(_expression(condition), field_types, now=now)


def compile_condition(condition, field_types=None, *, now=None):
    if isinstance(condition, FilterPlan):
        return condition.sql()
    if field_types is None:
        raise FilterValidationError("SQL compilation requires a validated FilterPlan")
    return validate_condition(condition, field_types, now=now).sql()
