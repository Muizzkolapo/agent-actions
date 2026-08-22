"""Expectation, Suite, Outcome and SuiteResult model behaviour."""

import pytest
from pydantic import ValidationError

from agent_actions.expectations.types import Expectation, Outcome, Suite, SuiteResult


def test_resolved_id_uses_explicit_id_when_given():
    exp = Expectation(id="option_count", type="item_count", field="options", params={"equals": 4})
    assert exp.resolved_id == "option_count"


def test_resolved_id_is_derived_when_id_omitted():
    exp = Expectation(type="item_count", field="options", params={"equals": 4})
    assert exp.resolved_id.startswith("item_count_")
    assert len(exp.resolved_id) > len("item_count_")


def test_resolved_id_treats_an_explicit_empty_string_id_as_given_not_omitted():
    exp = Expectation(id="", type="item_count", field="options", params={"equals": 4})
    assert exp.resolved_id == ""


def test_definition_hash_ignores_id_but_tracks_params():
    a = Expectation(id="one", type="item_count", field="options", params={"equals": 4})
    b = Expectation(id="two", type="item_count", field="options", params={"equals": 4})
    c = Expectation(id="one", type="item_count", field="options", params={"equals": 5})
    assert a.definition_hash() == b.definition_hash()
    assert a.definition_hash() != c.definition_hash()


def test_definition_hash_tracks_hint():
    a = Expectation(
        type="item_count", field="options", params={"equals": 4}, hint="add more options"
    )
    b = Expectation(
        type="item_count", field="options", params={"equals": 4}, hint="different remedy text"
    )
    assert a.definition_hash() != b.definition_hash()


def test_definition_hash_tracks_type_field_and_severity():
    args = {"params": {"equals": 4}, "severity": "error"}
    base = Expectation(type="item_count", field="options", **args)
    diff_type = Expectation(type="word_count_between", field="options", **args)
    diff_field = Expectation(type="item_count", field="answer", **args)
    diff_severity = Expectation(
        type="item_count", field="options", params={"equals": 4}, severity="warn"
    )
    hashes = {
        base.definition_hash(),
        diff_type.definition_hash(),
        diff_field.definition_hash(),
        diff_severity.definition_hash(),
    }
    assert len(hashes) == 4


def test_severity_rejects_unknown_level():
    with pytest.raises(ValidationError):
        Expectation(type="not_null", field="answer", severity="critical")


def _outcome(oid, passed, severity="error"):
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


def test_overall_pass_is_false_when_an_error_severity_expectation_fails():
    result = SuiteResult(suite_name="s", outcomes=[_outcome("a", True), _outcome("b", False)])
    assert result.overall_pass is False


def test_failed_lists_every_failing_outcome_regardless_of_severity():
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("a", False), _outcome("b", False, "warn"), _outcome("c", True)],
    )
    assert [o.id for o in result.failed] == ["a", "b"]


def test_to_record_dict_reports_only_error_severity_ids_as_failed():
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


def test_two_rules_may_not_share_an_id():
    with pytest.raises(ValidationError, match="present"):
        Suite(
            name="s",
            expectations=[
                {"id": "present", "type": "not_null", "field": "a"},
                {"id": "present", "type": "not_null", "field": "b"},
            ],
        )


def test_rules_without_ids_do_not_collide():
    suite = Suite(
        name="s",
        expectations=[
            {"type": "not_null", "field": "a"},
            {"type": "not_null", "field": "b"},
        ],
    )
    assert len({e.resolved_id for e in suite.expectations}) == 2


def test_outcome_skipped_defaults_to_false():
    outcome = _outcome("a", True)
    assert outcome.skipped is False


def test_outcome_accepts_skipped_true():
    outcome = Outcome(
        id="a",
        type="llm_judge",
        severity="fail",
        passed=False,
        skipped=True,
        detail="judge budget exhausted: 10/10 calls used this run",
        definition_hash="abc123",
    )
    assert outcome.skipped is True
    assert outcome.passed is False


def test_skipped_fail_severity_outcome_still_blocks_overall_pass():
    skipped = Outcome(
        id="a",
        type="llm_judge",
        severity="fail",
        passed=False,
        skipped=True,
        detail="judge budget exhausted",
        definition_hash="abc123",
    )
    result = SuiteResult(suite_name="s", outcomes=[skipped])
    assert result.overall_pass is False


def test_to_record_dict_lists_skipped_ids_separately_from_failed():
    skipped = Outcome(
        id="a",
        type="llm_judge",
        severity="fail",
        passed=False,
        skipped=True,
        detail="judge budget exhausted",
        definition_hash="abc123",
    )
    genuinely_failed = _outcome("b", False)
    result = SuiteResult(suite_name="s", outcomes=[skipped, genuinely_failed])
    payload = result.to_record_dict()
    assert payload["skipped"] == ["a"]
    assert payload["failed"] == ["a", "b"]


def test_to_record_dict_skipped_excludes_warn_and_info_severity():
    skipped_info = Outcome(
        id="a",
        type="llm_judge",
        severity="info",
        passed=False,
        skipped=True,
        detail="judge budget exhausted",
        definition_hash="abc123",
    )
    result = SuiteResult(suite_name="s", outcomes=[skipped_info])
    payload = result.to_record_dict()
    assert payload["skipped"] == []
