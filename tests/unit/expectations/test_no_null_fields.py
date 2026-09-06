"""The record-scoped rule that no field came back null."""

from __future__ import annotations

import pytest

from agent_actions.expectations import registry
from agent_actions.expectations.runner import run_suite
from agent_actions.expectations.types import Expectation, Suite


def check(record, **params):
    return registry.get("no_null_fields").check(record, params)


def test_a_record_with_no_nulls_passes():
    passed, detail = check({"title": "Outage", "severity": 3})
    assert passed is True
    assert detail == ""


def test_a_null_field_fails_and_the_detail_names_it():
    passed, detail = check({"title": "Outage", "severity": None})
    assert passed is False
    assert "severity" in detail
    assert "title" not in detail


def test_the_detail_names_every_null_field_not_just_the_first():
    _, detail = check({"a": None, "b": None, "c": 1})
    assert "a" in detail and "b" in detail


def test_framework_fields_are_ignored():
    """A leading underscore marks a framework field, which the model did not fill."""
    passed, _ = check({"title": "Outage", "_recovery": None})
    assert passed is True


def test_an_excluded_field_may_be_null():
    passed, _ = check({"title": "Outage", "notes": None}, exclude=["notes"])
    assert passed is True


def test_exclude_does_not_waive_other_fields():
    passed, detail = check({"notes": None, "severity": None}, exclude=["notes"])
    assert passed is False
    assert "severity" in detail
    assert "notes" not in detail


def test_an_empty_record_fails():
    """No fields means nothing was produced, which is not the same as nothing being null."""
    passed, detail = check({})
    assert passed is False
    assert detail


def test_a_record_of_only_framework_fields_fails():
    passed, _ = check({"_recovery": {"x": 1}})
    assert passed is False


@pytest.mark.parametrize("empty", ["", [], {}])
def test_empty_values_are_not_null(empty):
    """not_null rejects empty; this rule is about null only, so they differ deliberately."""
    passed, _ = check({"title": empty})
    assert passed is True


def test_it_is_registered_record_scoped_and_takes_no_field():
    assert registry.is_record_scoped("no_null_fields") is True
    with pytest.raises(ValueError, match="does not take field:"):
        Expectation(id="r", type="no_null_fields", field="title")


def test_it_runs_through_a_suite_and_reports_a_failing_outcome():
    suite = Suite(name="s", expectations=[Expectation(id="no_nulls", type="no_null_fields")])

    result = run_suite(suite, {"title": "Outage", "severity": None})

    assert result.overall_pass is False
    assert [o.id for o in result.failed] == ["no_nulls"]
    assert "severity" in result.outcomes[0].detail


def test_exclude_reaches_the_check_through_a_suite():
    suite = Suite(
        name="s",
        expectations=[
            Expectation(id="no_nulls", type="no_null_fields", params={"exclude": ["severity"]})
        ],
    )

    assert run_suite(suite, {"title": "Outage", "severity": None}).overall_pass is True


def _preflight(entry):
    from agent_actions.validation.expectations_validator import find_expectation_defects

    # An action with no defects is absent from the mapping, not present and empty.
    return find_expectation_defects(
        {"act": {"expect": {"expectations": [entry]}}},
        {"act": {"title", "severity"}},
    ).get("act", [])


def test_preflight_accepts_the_rule_with_no_field_and_an_exclude_list():
    assert _preflight({"id": "r", "type": "no_null_fields", "params": {"exclude": ["notes"]}}) == []


def test_preflight_refuses_an_unknown_argument():
    """The registration is what preflight reads, so `exclude` is known and `excluded` is not."""
    defects = _preflight({"id": "r", "type": "no_null_fields", "params": {"excluded": ["notes"]}})
    assert any("excluded" in d for d in defects)


def test_preflight_refuses_a_field_selector_on_it():
    defects = _preflight({"id": "r", "type": "no_null_fields", "field": "title"})
    assert any("field" in d for d in defects)


# The oracle from the reprompt baseline: these are the cases the examples'
# check_required_fields decides, and this rule has to decide them the same way.
@pytest.mark.parametrize(
    "record,expected",
    [
        ({"title": "Outage", "severity": 3}, True),
        ({"title": "Outage", "severity": None}, False),
        ({"severity": None}, False),
        ({"title": "Outage", "_internal": None}, True),
        ({}, False),
    ],
)
def test_it_matches_the_examples_required_fields_udf(record, expected):
    passed, _ = check(record)
    assert passed is expected
