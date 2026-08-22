"""Expectation, Suite, Outcome and SuiteResult model behaviour."""

import pytest
from pydantic import ValidationError

from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult


def test_expectation_keeps_type_specific_params_out_of_declared_fields():
    exp = Expectation(id="option_count", type="item_count", field="options", equals=4)
    assert exp.params() == {"equals": 4}


def test_resolved_id_uses_explicit_id_when_given():
    exp = Expectation(id="option_count", type="item_count", field="options", equals=4)
    assert exp.resolved_id == "option_count"


def test_resolved_id_is_derived_when_id_omitted():
    exp = Expectation(type="item_count", field="options", equals=4)
    assert exp.resolved_id.startswith("item_count_")
    assert len(exp.resolved_id) > len("item_count_")


def test_resolved_id_treats_an_explicit_empty_string_id_as_given_not_omitted():
    exp = Expectation(id="", type="item_count", field="options", equals=4)
    assert exp.resolved_id == ""


def test_definition_hash_ignores_id_but_tracks_params():
    a = Expectation(id="one", type="item_count", field="options", equals=4)
    b = Expectation(id="two", type="item_count", field="options", equals=4)
    c = Expectation(id="one", type="item_count", field="options", equals=5)
    assert a.definition_hash() == b.definition_hash()
    assert a.definition_hash() != c.definition_hash()


def test_definition_hash_is_independent_of_extra_param_order():
    a = Expectation(id="one", type="item_count", field="options", equals=4, min=1)
    b = Expectation(min=1, equals=4, field="options", type="item_count", id="two")
    assert a.definition_hash() == b.definition_hash()


def test_definition_hash_tracks_hint():
    a = Expectation(type="item_count", field="options", equals=4, hint="add more options")
    b = Expectation(type="item_count", field="options", equals=4, hint="different remedy text")
    assert a.definition_hash() != b.definition_hash()


def test_definition_hash_tracks_type_field_and_severity():
    base = Expectation(type="item_count", field="options", severity="fail", equals=4)
    diff_type = Expectation(type="word_count_between", field="options", severity="fail", equals=4)
    diff_field = Expectation(type="item_count", field="answer", severity="fail", equals=4)
    diff_severity = Expectation(type="item_count", field="options", severity="warn", equals=4)
    hashes = {
        base.definition_hash(),
        diff_type.definition_hash(),
        diff_field.definition_hash(),
        diff_severity.definition_hash(),
    }
    assert len(hashes) == 4


def test_severity_defaults_to_fail():
    assert Expectation(type="not_null", field="answer").severity == "fail"


def test_severity_rejects_unknown_level():
    with pytest.raises(ValidationError):
        Expectation(type="not_null", field="answer", severity="critical")


def _outcome(oid, passed, severity="fail"):
    return Outcome(
        id=oid,
        type="item_count",
        severity=severity,
        passed=passed,
        detail="",
        definition_hash="abc123",
    )


def test_overall_pass_is_true_when_only_warn_and_info_fail():
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("a", True), _outcome("b", False, "warn"), _outcome("c", False, "info")],
    )
    assert result.overall_pass is True


def test_overall_pass_is_false_when_a_fail_severity_expectation_fails():
    result = SuiteResult(suite_name="s", outcomes=[_outcome("a", True), _outcome("b", False)])
    assert result.overall_pass is False


def test_failed_lists_every_failing_outcome_regardless_of_severity():
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("a", False), _outcome("b", False, "warn"), _outcome("c", True)],
    )
    assert [o.id for o in result.failed] == ["a", "b"]


def test_to_record_dict_reports_only_fail_severity_ids_as_failed():
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("a", False), _outcome("b", False, "warn"), _outcome("c", True)],
    )
    payload = result.to_record_dict()
    assert payload["overall_pass"] is False
    assert payload["failed"] == ["a"]
    assert len(payload["outcomes"]) == 3


def test_suite_requires_at_least_one_expectation():
    with pytest.raises(ValidationError):
        Suite(name="empty", expectations=[])
