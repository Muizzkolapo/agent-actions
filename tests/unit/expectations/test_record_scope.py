"""Record-scoped expectation types: registration, rule shape, and dispatch."""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.expectations import registry
from agent_actions.expectations.runner import run_suite
from agent_actions.expectations.types import Expectation, Suite


@pytest.fixture
def record_scoped_type():
    """A record-scoped type registered for one test, then removed."""
    name = "_test_record_scoped"
    seen: list[Any] = []

    def check(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
        seen.append(value)
        return bool(params.get("want_pass", True)), f"saw {type(value).__name__}"

    registry._REGISTRY[name] = registry.ExpectationType(
        name, frozenset({"want_pass"}), frozenset(), check, scope="record"
    )
    try:
        yield name, seen
    finally:
        registry._REGISTRY.pop(name, None)


def test_a_record_scoped_check_receives_the_whole_record(record_scoped_type):
    name, seen = record_scoped_type
    suite = Suite(name="s", expectations=[Expectation(id="r", type=name)])
    record = {"a": 1, "b": None}

    run_suite(suite, record)

    assert seen == [record]


def test_a_record_scoped_failure_reports_its_detail(record_scoped_type):
    name, _ = record_scoped_type
    suite = Suite(
        name="s",
        expectations=[Expectation(id="r", type=name, params={"want_pass": False})],
    )

    result = run_suite(suite, {"a": 1})

    assert result.overall_pass is False
    assert [o.id for o in result.failed] == ["r"]
    assert result.outcomes[0].detail == "saw dict"


def test_a_record_scoped_rule_refuses_a_field_selector(record_scoped_type):
    name, _ = record_scoped_type
    with pytest.raises(ValueError, match="does not take field:"):
        Expectation(id="r", type=name, field="a")


def test_a_record_scoped_rule_is_valid_without_a_field_selector(record_scoped_type):
    name, _ = record_scoped_type
    assert Expectation(id="r", type=name).field is None


def test_a_field_scoped_rule_still_requires_a_field_selector():
    with pytest.raises(ValueError, match="requires field:"):
        Expectation(id="r", type="not_null")


def test_row_condition_still_gates_a_record_scoped_rule(record_scoped_type):
    name, seen = record_scoped_type
    suite = Suite(
        name="s",
        expectations=[Expectation(id="r", type=name, params={"row_condition": "a == 99"})],
    )

    result = run_suite(suite, {"a": 1})

    assert seen == []
    assert result.outcomes[0].skipped is True
    assert result.outcomes[0].passed is True


def test_expression_is_registered_as_record_scoped():
    """`expression` was the hardcoded exception; it becomes an ordinary registration."""
    assert registry.is_record_scoped("expression") is True


@pytest.mark.parametrize("type_name", ["not_null", "llm_judge", "matches_regex"])
def test_field_scoped_types_are_not_record_scoped(type_name: str):
    assert registry.is_record_scoped(type_name) is False


def test_an_unregistered_type_is_not_record_scoped():
    """Rule-shape validation runs before the runner reports the unknown type."""
    assert registry.is_record_scoped("_no_such_type") is False


def test_expression_still_evaluates_against_the_whole_record():
    suite = Suite(
        name="s",
        expectations=[
            Expectation(id="e", type="expression", params={"condition": "score > 5"}),
        ],
    )

    assert run_suite(suite, {"score": 9}).overall_pass is True
    assert run_suite(suite, {"score": 1}).overall_pass is False
