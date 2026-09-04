"""Running a suite over a record."""

from unittest.mock import patch

import pytest

from agent_actions.expectations.runner import UnknownExpectationTypeError, run_suite
from agent_actions.expectations.types import Suite

RECORD = {
    "options": ["alpha one", "beta two", "gamma three", "delta four"],
    "answer_explanation": "per the documentation",
    "answer": "alpha one",
}


def suite_of(*entries):
    return Suite(name="s", expectations=list(entries))


def test_all_passing_gives_overall_pass_and_no_failures():
    result = run_suite(
        suite_of(
            {"id": "count", "type": "item_count", "field": "options", "params": {"equals": 4}},
            {
                "id": "phrasing",
                "type": "no_forbidden_phrases",
                "field": "answer_explanation",
                "params": {"phrases": ["the source"]},
            },
        ),
        RECORD,
    )
    assert result.overall_pass is True
    assert result.failed == []
    assert len(result.outcomes) == 2


def test_a_failing_error_severity_rule_blocks_and_carries_detail():
    result = run_suite(
        suite_of(
            {"id": "count", "type": "item_count", "field": "options", "params": {"equals": 5}}
        ),
        RECORD,
    )
    assert result.overall_pass is False
    assert result.failed[0].id == "count"
    assert "5" in result.failed[0].detail and "4" in result.failed[0].detail


def test_a_failing_warn_severity_rule_is_recorded_but_does_not_block():
    result = run_suite(
        suite_of(
            {
                "id": "count",
                "type": "item_count",
                "field": "options",
                "params": {"equals": 5},
                "severity": "warn",
            }
        ),
        RECORD,
    )
    assert result.overall_pass is True
    assert result.failed[0].id == "count"


def test_wildcard_selector_fails_when_any_element_fails_and_reports_each():
    result = run_suite(
        suite_of(
            {"id": "len", "type": "word_count_between", "field": "options[*]", "params": {"max": 1}}
        ),
        RECORD,
    )
    assert result.overall_pass is False
    assert result.failed[0].detail.count("expected at most 1") == 4


def test_wildcard_selector_passes_when_every_element_passes():
    result = run_suite(
        suite_of(
            {"id": "len", "type": "word_count_between", "field": "options[*]", "params": {"max": 5}}
        ),
        RECORD,
    )
    assert result.overall_pass is True


def test_missing_field_becomes_a_failed_outcome_not_an_exception():
    result = run_suite(suite_of({"id": "missing", "type": "not_null", "field": "absent"}), RECORD)
    assert result.overall_pass is False
    assert "absent" in result.failed[0].detail


def test_unknown_type_raises_because_preflight_should_have_refused_it():
    with pytest.raises(UnknownExpectationTypeError, match="no_such_type"):
        run_suite(suite_of({"id": "x", "type": "no_such_type", "field": "answer"}), RECORD)


def test_outcome_carries_the_definition_hash_of_the_rule_that_produced_it():
    suite = suite_of(
        {"id": "count", "type": "item_count", "field": "options", "params": {"equals": 4}}
    )
    result = run_suite(suite, RECORD)
    assert result.outcomes[0].definition_hash == suite.expectations[0].definition_hash()


def test_derived_ids_appear_in_outcomes_when_id_is_omitted():
    result = run_suite(
        suite_of({"type": "item_count", "field": "options", "params": {"equals": 4}}), RECORD
    )
    assert result.outcomes[0].id.startswith("item_count_")


def test_suite_name_is_carried_onto_the_result():
    assert run_suite(suite_of({"type": "not_null", "field": "answer"}), RECORD).suite_name == "s"


def test_every_expectation_runs_even_after_an_earlier_one_fails():
    result = run_suite(
        suite_of(
            {"id": "a", "type": "item_count", "field": "options", "params": {"equals": 99}},
            {"id": "b", "type": "not_null", "field": "answer"},
        ),
        RECORD,
    )
    assert [o.id for o in result.outcomes] == ["a", "b"]
    assert result.outcomes[1].passed is True


def fake_judge_always(passed, detail="from judge", skipped=False):
    def dispatch(expectation, value, context):
        return passed, detail, skipped

    return dispatch


def recording_judge(results):
    """Returns each result in *results* in order, recording (value, context) calls."""
    calls = []
    it = iter(results)

    def dispatch(expectation, value, context):
        calls.append((value, context))
        return next(it)

    dispatch.calls = calls
    return dispatch


def test_llm_judge_dispatches_through_the_injected_judge():
    result = run_suite(
        suite_of(
            {"id": "on_topic", "type": "llm_judge", "field": "answer", "params": {"rule": "r"}}
        ),
        RECORD,
        judge=fake_judge_always(True, "meets the rule"),
    )
    assert result.overall_pass is True
    assert result.outcomes[0].detail == "meets the rule"


def test_llm_judge_failing_verdict_blocks_the_suite():
    result = run_suite(
        suite_of(
            {"id": "on_topic", "type": "llm_judge", "field": "answer", "params": {"rule": "r"}}
        ),
        RECORD,
        judge=fake_judge_always(False, "too vague"),
    )
    assert result.overall_pass is False
    assert result.outcomes[0].detail == "too vague"
    assert result.outcomes[0].skipped is False


def test_llm_judge_skipped_verdict_is_marked_skipped_and_still_blocks():
    result = run_suite(
        suite_of(
            {"id": "on_topic", "type": "llm_judge", "field": "answer", "params": {"rule": "r"}}
        ),
        RECORD,
        judge=fake_judge_always(False, "judge budget exhausted", skipped=True),
    )
    assert result.overall_pass is False
    assert result.outcomes[0].skipped is True


def test_llm_judge_without_a_judge_dispatcher_raises():
    with pytest.raises(ValueError, match="llm_judge"):
        run_suite(
            suite_of(
                {"id": "on_topic", "type": "llm_judge", "field": "answer", "params": {"rule": "r"}}
            ),
            RECORD,
        )


def test_llm_judge_wildcard_selector_calls_judge_once_per_element():
    judge = recording_judge([(True, "ok", False)] * 4)
    result = run_suite(
        suite_of(
            {"id": "each", "type": "llm_judge", "field": "options[*]", "params": {"rule": "r"}}
        ),
        RECORD,
        judge=judge,
    )
    assert result.overall_pass is True
    assert len(judge.calls) == 4


def test_llm_judge_wildcard_skipped_if_any_element_was_skipped():
    judge = recording_judge(
        [
            (True, "ok", False),
            (False, "budget exhausted", True),
            (True, "ok", False),
            (True, "ok", False),
        ]
    )
    result = run_suite(
        suite_of(
            {"id": "each", "type": "llm_judge", "field": "options[*]", "params": {"rule": "r"}}
        ),
        RECORD,
        judge=judge,
    )
    assert result.overall_pass is False
    assert result.outcomes[0].skipped is True


def test_llm_judge_context_ref_is_resolved_and_passed_to_the_judge():
    judge = recording_judge([(True, "ok", False)])
    context_source = {"extract_context": {"source_context": "the docs say X"}}
    run_suite(
        suite_of(
            {
                "id": "grounded",
                "type": "llm_judge",
                "field": "answer",
                "params": {"rule": "r", "context": ["extract_context.source_context"]},
            }
        ),
        RECORD,
        judge=judge,
        context_source=context_source,
    )
    assert judge.calls[0][1] == {"extract_context.source_context": "the docs say X"}


def test_llm_judge_context_ref_with_no_context_source_is_a_failed_outcome_not_a_crash():
    result = run_suite(
        suite_of(
            {
                "id": "grounded",
                "type": "llm_judge",
                "field": "answer",
                "params": {"rule": "r", "context": ["extract_context.source_context"]},
            }
        ),
        RECORD,
        judge=fake_judge_always(True),
    )
    assert result.overall_pass is False
    assert "context source" in result.outcomes[0].detail


def test_llm_judge_unresolvable_context_ref_is_a_failed_outcome_not_a_crash():
    result = run_suite(
        suite_of(
            {
                "id": "grounded",
                "type": "llm_judge",
                "field": "answer",
                "params": {"rule": "r", "context": ["missing_action.missing_field"]},
            }
        ),
        RECORD,
        judge=fake_judge_always(True),
        context_source={"extract_context": {"source_context": "x"}},
    )
    assert result.overall_pass is False
    assert "missing_action" in result.outcomes[0].detail


def test_llm_judge_without_context_declared_never_calls_resolve_context():
    judge = recording_judge([(True, "ok", False)])
    with patch("agent_actions.expectations.runner.resolve_context") as mock_resolve:
        run_suite(
            suite_of(
                {"id": "plain", "type": "llm_judge", "field": "answer", "params": {"rule": "r"}}
            ),
            RECORD,
            judge=judge,
            context_source={"some_action": {"some_field": "present but unrelated"}},
        )
    mock_resolve.assert_not_called()
    assert judge.calls[0][1] is None
