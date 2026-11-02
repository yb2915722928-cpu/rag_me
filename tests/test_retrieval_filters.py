"""Public typed-filter contract; authored only, never executed for #84."""
from datetime import datetime, timezone
import importlib

import pytest

filters = importlib.import_module("app.modules.4_retrievalAndFusion.typed_filters")
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
FIELDS = {"product": "string", "price": "number", "enabled": "boolean",
          "starts": "datetime", "tags": "set[string]"}


def test_grouping_types_and_missing_null_have_one_public_contract():
    plan = filters.compile_filter({"and": [
        {"or": [{"field": "product", "op": "in", "value": ["AX-100", "USB-C"]},
                {"field": "tags", "op": "contains", "value": "manual"}]},
        {"field": "price", "op": "range", "lower": 10, "upper": 20},
        {"field": "enabled", "op": "eq", "value": True},
    ]}, FIELDS, now=NOW)
    assert plan.matches({"product": "AX-100", "price": 10, "enabled": True})
    assert plan.matches({"tags": ["manual"], "price": 19, "enabled": True})
    assert not plan.matches({"product": "AX-100", "price": 20, "enabled": True})
    assert not plan.matches({"product": "AX-100", "price": None, "enabled": True})
    assert not plan.matches({"product": "AX-100", "enabled": True})


@pytest.mark.parametrize("op,expected", [("exists", [False, True, True]),
                                         ("missing", [True, False, False]),
                                         ("is_null", [False, True, False])])
def test_presence_is_distinct_from_explicit_null(op, expected):
    plan = filters.compile_filter({"field": "price", "op": op}, FIELDS)
    assert [plan.matches(row) for row in ({}, {"price": None}, {"price": 0})] == expected


def test_fixed_now_and_half_open_timezone_range():
    plan = filters.compile_filter({"field": "starts", "op": "range",
                                   "lower": "2026-11-02T17:00:00+08:00",
                                   "upper": {"now": True}}, FIELDS, now=NOW)
    assert plan.now == NOW
    assert plan.matches({"starts": "2026-11-02T09:00:00Z"})
    assert not plan.matches({"starts": "2026-11-02T18:00:00+08:00"})


@pytest.mark.parametrize("condition", [
    {"field": "unknown", "op": "eq", "value": "x"},
    {"field": "price", "op": "eq", "value": True},
    {"field": "price", "op": "eq", "value": None},
    {"field": "price", "op": "eq", "value": float("nan")},
    {"field": "starts", "op": "eq", "value": "2026-11-02T10:00:00"},
    {"field": "product", "op": "contains", "value": "x"},
    {"field": "tags", "op": "in", "value": ["x"]},
    {"field": "enabled", "op": "range", "lower": False},
    {"field": "price", "op": "eq", "value": 1, "ignored": 2},
    {"or": []},
])
def test_invalid_filters_are_rejected_before_execution(condition):
    with pytest.raises(filters.FilterValidationError):
        filters.compile_filter(condition, FIELDS)


@pytest.mark.parametrize("kind,left,right", [
    ("set[string]", ["x", "x", "y"], ["y", "x"]),
    ("set[number]", [1, 2.0], [2, 1.0]),
    ("set[boolean]", [True, False], [False, True]),
    ("set[datetime]", ["2026-11-02T18:00:00+08:00"], ["2026-11-02T10:00:00Z"]),
])
def test_set_equality_ignores_order_and_duplicate_members(kind, left, right):
    plan = filters.compile_filter({"field": "values", "op": "eq", "value": right}, {"values": kind})
    assert plan.matches({"values": left})
    assert not plan.matches({"values": None})
    assert not plan.matches({})


def test_sql_values_are_bound_and_boolean_groups_preserved():
    plan = filters.compile_filter({"or": [
        {"field": "product", "op": "eq", "value": "' OR TRUE --"},
        {"field": "price", "op": "missing"},
    ]}, FIELDS)
    sql, params = plan.sql("c.metadata")
    assert "' OR TRUE --" not in sql
    assert "' OR TRUE --" in params
    assert " OR " in sql
    with pytest.raises(filters.FilterValidationError):
        plan.sql("metadata); DROP TABLE content; --")
