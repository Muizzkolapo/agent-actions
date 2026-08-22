"""Running a suite over a record."""

from unittest.mock import patch

import pytest

from agent_actions.expectations import registry
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


def test_expression_true_produces_a_passing_outcome():
    suite = Suite(
        name="s",
        expectations=[
            {"id": "score_floor", "type": "expression", "params": {"condition": "score >= 80"}}
        ],
    )
    result = run_suite(suite, {"score": 91})
    assert result.overall_pass is True
    assert result.outcomes[0].passed is True
    assert result.outcomes[0].detail == ""


def test_expression_false_outcome_detail_names_values():
    suite = Suite(
        name="s",
        expectations=[
            {"id": "score_floor", "type": "expression", "params": {"condition": "score >= 80"}}
        ],
    )
    result = run_suite(suite, {"score": 64})
    assert result.overall_pass is False
    assert result.outcomes[0].passed is False
    assert "score=64" in result.outcomes[0].detail


def test_expression_missing_field_is_a_failed_outcome_not_a_crash():
    suite = Suite(
        name="s",
        expectations=[
            {"id": "score_floor", "type": "expression", "params": {"condition": "score >= 80"}}
        ],
    )
    result = run_suite(suite, {"points": 90})
    assert result.outcomes[0].passed is False
    assert "does not exist" in result.outcomes[0].detail


def test_expression_warn_severity_does_not_block_overall_pass():
    suite = Suite(
        name="s",
        expectations=[
            {
                "id": "score_floor",
                "type": "expression",
                "params": {"condition": "score >= 80"},
                "severity": "warn",
            }
        ],
    )
    result = run_suite(suite, {"score": 10})
    assert result.outcomes[0].passed is False
    assert result.overall_pass is True


def test_expression_runs_alongside_deterministic_checks_in_one_suite():
    suite = Suite(
        name="s",
        expectations=[
            {"id": "has_ideas", "type": "item_count", "field": "ideas", "params": {"min": 1}},
            {"id": "score_floor", "type": "expression", "params": {"condition": "score >= 80"}},
        ],
    )
    result = run_suite(suite, {"ideas": ["a"], "score": 95})
    assert [o.passed for o in result.outcomes] == [True, True]


def test_expression_entry_loads_from_a_schema_files_expectations_block():
    from agent_actions.expectations.loader import build_suite_from_schema_data

    suite = build_suite_from_schema_data(
        "quality",
        {
            "expectations": [
                {"id": "score_floor", "type": "expression", "params": {"condition": "score >= 80"}}
            ]
        },
    )
    result = run_suite(suite, {"score": 85})
    assert result.overall_pass is True


def test_two_expressions_and_a_judged_rule_coexist_in_one_suite():
    suite = Suite(
        name="s",
        expectations=[
            {"id": "floor", "type": "expression", "params": {"condition": "score >= 10"}},
            {"id": "cap", "type": "expression", "params": {"condition": "score <= 90"}},
            {
                "id": "on_topic",
                "type": "llm_judge",
                "field": "title",
                "params": {"rule": "on topic"},
            },
        ],
    )
    result = run_suite(
        suite, {"score": 120, "title": "t"}, judge=lambda e, v, c: (True, "ok", False)
    )
    assert [o.passed for o in result.outcomes] == [True, False, True]
    assert "score=120" in result.outcomes[1].detail


def test_hint_on_an_expression_entry_stays_out_of_condition_params():
    suite = Suite(
        name="s",
        expectations=[
            {
                "id": "floor",
                "type": "expression",
                "params": {"condition": "score >= 10"},
                "hint": "raise the score",
            }
        ],
    )
    result = run_suite(suite, {"score": 50})
    assert result.outcomes[0].passed is True


def test_a_rule_whose_row_condition_is_false_is_skipped_not_failed():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "item_count",
                "field": "options",
                "params": {"equals": 99, "row_condition": "answer == 'not this record'"},
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].skipped is True
    assert result.outcomes[0].passed is True
    assert result.overall_pass is True


def test_a_skipped_row_condition_names_the_condition_that_gated_it():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "item_count",
                "field": "options",
                "params": {"equals": 99, "row_condition": "answer == 'other'"},
            }
        ),
        RECORD,
    )
    assert "row_condition" in result.outcomes[0].detail


def test_a_rule_whose_row_condition_holds_still_runs_and_can_fail():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "item_count",
                "field": "options",
                "params": {"equals": 99, "row_condition": "answer == 'alpha one'"},
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].skipped is False
    assert result.overall_pass is False


def test_the_row_condition_is_not_handed_to_the_check_as_an_argument():
    seen = {}

    def spy(value, params):
        seen.update(params)
        return True, ""

    registry._REGISTRY["row_condition_spy"] = registry.ExpectationType(
        "row_condition_spy", frozenset(), frozenset(), spy
    )
    try:
        run_suite(
            suite_of(
                {
                    "type": "row_condition_spy",
                    "field": "answer",
                    "params": {"row_condition": "answer == 'alpha one'"},
                }
            ),
            RECORD,
        )
    finally:
        del registry._REGISTRY["row_condition_spy"]
    assert "row_condition" not in seen


def test_an_unparseable_row_condition_is_a_failed_outcome_not_a_crash():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "not_null",
                "field": "answer",
                "params": {"row_condition": "this is not a condition"},
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].passed is False
    assert result.outcomes[0].skipped is False


def test_a_row_condition_on_a_field_the_record_lacks_fails_rather_than_waives():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "not_null",
                "field": "answer",
                "params": {"row_condition": "has_citation == true"},
            }
        ),
        RECORD,
    )
    outcome = result.outcomes[0]
    assert outcome.passed is False
    assert outcome.skipped is False
    assert result.overall_pass is False
    assert "has_citation" in outcome.detail


def test_an_unquoted_literal_in_a_row_condition_fails_rather_than_waives():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "not_null",
                "field": "answer",
                "params": {"row_condition": "answer == pending"},
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].passed is False
    assert result.outcomes[0].skipped is False


def test_a_row_condition_gates_a_record_scoped_rule_too():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "expression",
                "params": {
                    "condition": "answer == 'never true'",
                    "row_condition": "answer == 'not this record'",
                },
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].skipped is True
    assert result.outcomes[0].passed is True


def test_a_gated_rule_whose_field_is_absent_is_skipped_not_a_resolution_failure():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "not_null",
                "field": "absent_field",
                "params": {"row_condition": "answer == 'not this record'"},
            }
        ),
        RECORD,
    )
    assert result.outcomes[0].skipped is True
    assert result.outcomes[0].passed is True


def test_a_rule_waived_by_its_row_condition_is_not_listed_as_unchecked():
    result = run_suite(
        suite_of(
            {
                "id": "gated",
                "type": "not_null",
                "field": "answer",
                "params": {"row_condition": "answer == 'not this record'"},
            }
        ),
        RECORD,
    )
    assert result.to_record_dict()["skipped"] == []
    assert result.to_record_dict()["overall_pass"] is True


def test_a_raising_user_check_is_a_failed_outcome_not_a_crash(preserve_registry):
    from agent_actions import expectation_check

    @expectation_check("explodes")
    def explodes(value, params):
        raise RuntimeError("boom")

    suite = Suite(name="s", expectations=[{"id": "e", "type": "explodes", "field": "title"}])
    result = run_suite(suite, {"title": "hello"})
    assert result.outcomes[0].passed is False
    assert result.outcomes[0].skipped is False
    assert "check raised RuntimeError: boom" in result.outcomes[0].detail


def test_a_raising_check_does_not_stop_later_expectations(preserve_registry):
    from agent_actions import expectation_check

    @expectation_check("explodes_first")
    def explodes_first(value, params):
        raise RuntimeError("boom")

    suite = Suite(
        name="s",
        expectations=[
            {"id": "e", "type": "explodes_first", "field": "title"},
            {"id": "count", "type": "item_count", "field": "ideas", "min": 1},
        ],
    )
    result = run_suite(suite, {"title": "hello", "ideas": ["a"]})
    assert [o.passed for o in result.outcomes] == [False, True]


def test_an_unvalidated_condition_parse_error_is_a_failed_outcome():
    # A condition preflight never validated (suite built programmatically)
    # must not crash the record; the parse rejection lands in the detail.
    suite = Suite(
        name="s",
        expectations=[{"id": "f", "type": "expression", "condition": "NO_SUCH_FN(score) > 0"}],
    )
    result = run_suite(suite, {"score": 5})
    assert result.outcomes[0].passed is False
    assert "check raised ExpressionParseError" in result.outcomes[0].detail


def test_missing_judge_dispatcher_still_raises():
    suite = Suite(
        name="s", expectations=[{"id": "j", "type": "llm_judge", "field": "title", "rule": "r"}]
    )
    with pytest.raises(ValueError, match="no judge"):
        run_suite(suite, {"title": "hello"})
