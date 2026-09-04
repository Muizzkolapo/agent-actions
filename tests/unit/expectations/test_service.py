"""Observe-mode execution and service construction."""

from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.expectations.service import (
    ExpectationService,
    create_expectation_service_from_config,
)
from agent_actions.expectations.types import Suite

SUITE = Suite(
    name="s",
    expectations=[{"id": "count", "type": "item_count", "field": "ideas", "params": {"min": 2}}],
)
INLINE = [{"type": "item_count", "field": "ideas", "params": {"min": 2}}]


def passing_llm(prompt):
    return {"ideas": ["a", "b", "c"]}, True


def failing_llm(prompt):
    return {"ideas": ["a"]}, True


def test_observe_mode_calls_the_llm_exactly_once():
    calls = []

    def counting(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    ExpectationService(SUITE, repair="none").execute(counting, "PROMPT")
    assert calls == ["PROMPT"]


def test_observe_mode_returns_the_response_unchanged_when_rules_fail():
    result = ExpectationService(SUITE, repair="none").execute(failing_llm, "PROMPT")
    assert result.response == {"ideas": ["a"]}
    assert result.executed is True
    assert result.iterations == 1


def test_observe_mode_reports_the_failure_in_the_suite_result():
    result = ExpectationService(SUITE, repair="none").execute(failing_llm, "PROMPT")
    assert result.suite_result.overall_pass is False
    assert [o.id for o in result.suite_result.failed] == ["count"]


def test_observe_mode_reports_a_pass():
    result = ExpectationService(SUITE, repair="none").execute(passing_llm, "PROMPT")
    assert result.suite_result.overall_pass is True


def test_a_guard_skipped_call_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ({"x": 1}, False), "P")
    assert result.executed is False
    assert result.suite_result is None


def test_a_none_response_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: (None, True), "P")
    assert result.suite_result is None


def test_a_non_dict_response_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ("text", True), "P")
    assert result.suite_result is None


def test_a_single_item_list_response_is_unwrapped_and_validated():
    # A real online record arrives as a length-1 list, not a bare dict.
    result = ExpectationService(SUITE, repair="none").execute(
        lambda p: ([{"ideas": ["a", "b", "c"]}], True), "P"
    )
    assert result.suite_result is not None
    assert result.suite_result.overall_pass is True
    assert result.response == {"ideas": ["a", "b", "c"]}


def test_a_multi_item_list_response_is_not_validated():
    # File-granularity (multiple records per call) has no expect: semantics
    # defined -- left alone, matching the existing not-a-dict skip behavior.
    result = ExpectationService(SUITE, repair="none").execute(
        lambda p: ([{"ideas": ["a"]}, {"ideas": ["b"]}], True), "P"
    )
    assert result.suite_result is None


def test_an_empty_list_response_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ([], True), "P")
    assert result.suite_result is None


def test_a_single_item_list_of_a_non_dict_is_not_validated():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: (["text"], True), "P")
    assert result.suite_result is None


def test_factory_returns_none_without_an_expect_block():
    assert create_expectation_service_from_config(None, action_name="a") is None


def test_factory_builds_an_inline_suite_named_after_the_action():
    service = create_expectation_service_from_config(
        {"expectations": INLINE, "repair": "none"}, action_name="brainstorm"
    )
    assert service.suite.name == "brainstorm:inline"


@pytest.mark.parametrize("mode", ["auto", "retry"])
def test_factory_refuses_repair_modes_this_build_does_not_implement(mode):
    with pytest.raises(ConfigurationError, match="repair: none"):
        create_expectation_service_from_config(
            {"expectations": INLINE, "repair": mode}, action_name="a"
        )


def test_factory_refuses_a_repair_prompt_mapping():
    with pytest.raises(ConfigurationError, match="repair: none"):
        create_expectation_service_from_config(
            {"expectations": INLINE, "repair": {"prompt": "$wf.Fix"}}, action_name="a"
        )


def _schema_project(tmp_path, name="quality"):
    import yaml

    (tmp_path / "agent_actions.yml").write_text(yaml.safe_dump({"schema_path": "schema"}))
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / f"{name}.yml").write_text(yaml.safe_dump({"expectations": INLINE}))
    return tmp_path


def test_factory_resolves_a_named_suite_through_the_schema_path(tmp_path):
    root = _schema_project(tmp_path)
    service = create_expectation_service_from_config(
        {"suite": "quality", "repair": "none"}, action_name="a", project_root=root
    )
    assert service.suite.name == "quality"


def test_factory_defaults_a_bare_expect_to_the_actions_schema(tmp_path):
    root = _schema_project(tmp_path)
    service = create_expectation_service_from_config(
        {"repair": "none"}, action_name="a", schema_name="quality", project_root=root
    )
    assert service.suite.name == "quality"


def test_factory_refuses_a_bare_expect_without_a_named_schema():
    with pytest.raises(ConfigurationError, match="bare expect"):
        create_expectation_service_from_config({"repair": "none"}, action_name="a")


def test_factory_refuses_a_named_suite_without_a_project_root():
    with pytest.raises(ConfigurationError, match="project root"):
        create_expectation_service_from_config(
            {"suite": "quality", "repair": "none"}, action_name="a"
        )


def test_factory_does_not_treat_an_empty_expect_dict_as_absent():
    with pytest.raises(ConfigurationError):
        create_expectation_service_from_config({}, action_name="a")


def test_factory_wraps_a_missing_suite_in_a_configuration_error(tmp_path):
    root = _schema_project(tmp_path)
    with pytest.raises(ConfigurationError, match="nothing_here"):
        create_expectation_service_from_config(
            {"suite": "nothing_here", "repair": "none"}, action_name="a", project_root=root
        )


def test_execute_threads_llm_context_to_a_judged_expectations_context_ref():
    from agent_actions.expectations.types import Suite as SuiteType

    grounded_suite = SuiteType(
        name="s",
        expectations=[
            {
                "id": "grounded",
                "type": "llm_judge",
                "field": "ideas",
                "params": {"rule": "r", "context": ["extract_context.source_context"]},
            }
        ],
    )

    captured = {}

    def fake_judge(expectation, value, context):
        captured["context"] = context
        return True, "ok", False

    service = ExpectationService(grounded_suite, repair="none", judge=fake_judge)
    result = service.execute(
        passing_llm,
        "PROMPT",
        llm_context={"extract_context": {"source_context": "docs say X"}},
    )
    assert result.suite_result.overall_pass is True
    assert captured["context"] == {"extract_context.source_context": "docs say X"}


def test_execute_without_llm_context_still_works_for_non_judged_suites():
    result = ExpectationService(SUITE, repair="none").execute(passing_llm, "PROMPT")
    assert result.suite_result.overall_pass is True


def test_factory_does_not_build_a_judge_for_a_purely_deterministic_suite():
    service = create_expectation_service_from_config(
        {"expectations": INLINE, "repair": "none"}, action_name="brainstorm"
    )
    assert service._judge is None


def test_factory_builds_a_judge_dispatcher_for_a_suite_with_llm_judge():
    judge_inline = [
        {"id": "on_topic", "type": "llm_judge", "field": "ideas", "params": {"rule": "on topic"}}
    ]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none"},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    assert service._judge is not None


def test_factory_judge_dispatcher_calls_through_to_invoke_judge_with_votes():
    judge_inline = [
        {"id": "on_topic", "type": "llm_judge", "field": "ideas", "params": {"rule": "on topic"}}
    ]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none"},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    with patch(
        "agent_actions.expectations.judge.invoke_judge_with_votes", return_value=(True, "ok")
    ) as mock_invoke:
        result = service.execute(lambda p: ({"ideas": ["a"]}, True), "PROMPT")
    assert result.suite_result.overall_pass is True
    mock_invoke.assert_called_once()


def test_factory_judge_budget_is_shared_across_every_record_the_service_processes():
    judge_inline = [
        {"id": "on_topic", "type": "llm_judge", "field": "ideas", "params": {"rule": "on topic"}}
    ]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none", "judge_budget": 1},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    with patch(
        "agent_actions.expectations.judge.invoke_judge_with_votes", return_value=(True, "ok")
    ):
        first = service.execute(lambda p: ({"ideas": ["a"]}, True), "PROMPT")
        second = service.execute(lambda p: ({"ideas": ["b"]}, True), "PROMPT")
    assert first.suite_result.overall_pass is True
    assert second.suite_result.outcomes[0].skipped is True
    assert second.suite_result.overall_pass is False


def test_a_cache_hit_bypasses_an_already_exhausted_budget():
    judge_inline = [
        {"id": "on_topic", "type": "llm_judge", "field": "ideas", "params": {"rule": "on topic"}}
    ]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none", "judge_budget": 1},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    with patch(
        "agent_actions.expectations.judge.invoke_judge_with_votes", return_value=(True, "ok")
    ) as mock_invoke:
        first = service.execute(lambda p: ({"ideas": ["a"]}, True), "PROMPT")
        # Same record content as the first call -- same cache key, budget already spent.
        second = service.execute(lambda p: ({"ideas": ["a"]}, True), "PROMPT")
    assert first.suite_result.overall_pass is True
    assert second.suite_result.overall_pass is True
    assert second.suite_result.outcomes[0].skipped is False
    mock_invoke.assert_called_once()


def test_factory_judge_dispatcher_survives_a_network_error_without_crashing_the_record():
    judge_inline = [
        {"id": "on_topic", "type": "llm_judge", "field": "ideas", "params": {"rule": "on topic"}}
    ]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none"},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    with patch(
        "agent_actions.expectations.judge.invoke_judge_with_votes",
        side_effect=ConnectionError("provider unreachable"),
    ):
        result = service.execute(lambda p: ({"ideas": ["a"]}, True), "PROMPT")
    assert result.suite_result.overall_pass is False
    assert result.suite_result.outcomes[0].skipped is False
    assert "provider unreachable" in result.suite_result.outcomes[0].detail


def test_retry_repair_regenerates_until_the_suite_passes():
    responses = iter([{"ideas": ["a"]}, {"ideas": ["a"]}, {"ideas": ["a", "b", "c"]}])
    calls = []

    def flaky(prompt):
        calls.append(prompt)
        return next(responses), True

    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    result = service.execute(flaky, "PROMPT")
    assert result.suite_result.overall_pass is True
    assert result.iterations == 3
    assert result.exhausted is False
    assert calls == ["PROMPT", "PROMPT", "PROMPT"]


def test_retry_repair_exits_on_first_pass_without_extra_calls():
    calls = []

    def counting(prompt):
        calls.append(prompt)
        return {"ideas": ["a", "b", "c"]}, True

    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    result = service.execute(counting, "PROMPT")
    assert result.iterations == 1
    assert len(calls) == 1


def test_retry_repair_exhausts_after_max_iterations():
    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    calls = []

    def always_bad(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    result = service.execute(always_bad, "PROMPT")
    assert len(calls) == 3
    assert result.iterations == 3
    assert result.exhausted is True
    assert result.suite_result.overall_pass is False
    assert result.response == {"ideas": ["a"]}


def test_warn_severity_failures_never_trigger_repair():
    warn_suite = Suite(
        name="s",
        expectations=[
            {
                "id": "count",
                "type": "item_count",
                "field": "ideas",
                "params": {"min": 2},
                "severity": "warn",
            }
        ],
    )
    calls = []

    def counting(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    result = ExpectationService(warn_suite, repair="retry", max_iterations=3).execute(
        counting, "PROMPT"
    )
    assert len(calls) == 1
    assert result.exhausted is False
    assert result.suite_result.overall_pass is True


def test_observe_mode_never_iterates_regardless_of_max_iterations():
    calls = []

    def counting(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    result = ExpectationService(SUITE, repair="none", max_iterations=3).execute(counting, "PROMPT")
    assert len(calls) == 1
    assert result.exhausted is False


def test_a_mid_loop_collapse_makes_exactly_two_calls():
    calls = []
    responses = iter([({"ideas": ["a"]}, True), (None, False)])

    def op(prompt):
        calls.append(prompt)
        return next(responses)

    ExpectationService(SUITE, repair="retry", max_iterations=3).execute(op, "PROMPT")
    assert len(calls) == 2


def test_a_mid_loop_collapse_keeps_the_last_failing_verdict():
    # Inner recovery (retry/reprompt) can exhaust to (None, False) on a later
    # iteration; a record that had data must not be downgraded below what
    # observe mode would have shipped.
    responses = iter([({"ideas": ["a"]}, True), (None, False)])
    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    result = service.execute(lambda p: next(responses), "PROMPT")
    assert result.executed is True
    assert result.response == {"ideas": ["a"]}
    assert result.suite_result is not None
    assert result.suite_result.overall_pass is False
    assert result.exhausted is True


def test_a_first_call_guard_skip_returns_unvalidated():
    calls = []

    def skipped(prompt):
        calls.append(prompt)
        return None, False

    result = ExpectationService(SUITE, repair="retry", max_iterations=3).execute(skipped, "P")
    assert result.executed is False
    assert result.response is None
    assert result.suite_result is None
    assert len(calls) == 1


def test_max_iterations_below_one_raises_at_construction():
    with pytest.raises(ValueError, match="max_iterations"):
        ExpectationService(SUITE, repair="retry", max_iterations=0)


def test_repair_with_max_iterations_one_validates_once_and_exhausts():
    calls = []

    def bad(prompt):
        calls.append(prompt)
        return {"ideas": ["a"]}, True

    result = ExpectationService(SUITE, repair="retry", max_iterations=1).execute(bad, "P")
    assert len(calls) == 1
    assert result.exhausted is True
    assert result.suite_result.overall_pass is False


def test_auto_repair_sends_a_composed_prompt_on_the_second_iteration():
    responses = iter([{"ideas": ["a"]}, {"ideas": ["a", "b", "c"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    service = ExpectationService(SUITE, repair="auto", max_iterations=3)
    result = service.execute(flaky, "ORIGINAL")
    assert result.suite_result.overall_pass is True
    assert prompts[0] == "ORIGINAL"
    assert prompts[1] != "ORIGINAL"
    assert "ORIGINAL" in prompts[1]
    assert "count" in prompts[1]
    assert '"ideas": ["a"]' in prompts[1]


def test_auto_repair_composes_from_the_latest_failing_response():
    responses = iter([{"ideas": ["first"]}, {"ideas": ["second"]}, {"ideas": ["a", "b", "c"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    ExpectationService(SUITE, repair="auto", max_iterations=3).execute(flaky, "O")
    assert "second" in prompts[2]
    assert "first" not in prompts[2]


def test_unknown_repair_value_is_rejected_at_construction():
    with pytest.raises(ValueError, match="repair must be"):
        ExpectationService(SUITE, repair={"prompt": "fix it"})


def test_retry_repair_still_uses_the_original_prompt_every_iteration():
    responses = iter([{"ideas": ["a"]}, {"ideas": ["a", "b", "c"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    ExpectationService(SUITE, repair="retry", max_iterations=3).execute(flaky, "ORIGINAL")
    assert prompts == ["ORIGINAL", "ORIGINAL"]


SCHEMA = {
    "type": "object",
    "properties": {"ideas": {"type": "array"}},
    "required": ["ideas"],
    "additionalProperties": False,
}


def test_schema_mismatch_under_repair_regenerates_with_feedback():
    responses = iter([{"wrong_key": 1}, {"ideas": ["a", "b", "c"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    service = ExpectationService(SUITE, repair="auto", max_iterations=3, schema=SCHEMA)
    result = service.execute(flaky, "ORIGINAL")
    assert result.suite_result.overall_pass is True
    assert result.iterations == 2
    assert "_structural" in prompts[1]
    assert "ideas" in prompts[1]


def test_a_schema_conforming_record_still_runs_the_semantic_suite():
    responses = iter([{"ideas": ["a"]}, {"ideas": ["a", "b", "c"]}])
    service = ExpectationService(SUITE, repair="retry", max_iterations=3, schema=SCHEMA)
    result = service.execute(lambda p: (next(responses), True), "P")
    assert result.suite_result.overall_pass is True
    assert result.iterations == 2


def test_non_record_response_under_repair_regenerates():
    responses = iter(["not json at all", {"ideas": ["a", "b", "c"]}])
    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    result = service.execute(lambda p: (next(responses), True), "P")
    assert result.suite_result.overall_pass is True
    assert result.iterations == 2


def test_non_record_feedback_names_the_expected_fields_under_auto():
    responses = iter(["plain text", {"ideas": ["a", "b", "c"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    ExpectationService(SUITE, repair="auto", max_iterations=3, schema=SCHEMA).execute(flaky, "O")
    assert "expected a JSON object" in prompts[1]
    assert "ideas" in prompts[1]


def test_schema_mismatch_in_observe_mode_is_not_checked():
    result = ExpectationService(SUITE, repair="none", schema=SCHEMA).execute(
        lambda p: ({"wrong_key": 1}, True), "P"
    )
    assert [o.id for o in result.suite_result.outcomes] == ["count"]


def test_structural_failure_skips_semantic_rules_that_iteration():
    service = ExpectationService(SUITE, repair="retry", max_iterations=1, schema=SCHEMA)
    result = service.execute(lambda p: ({"bad": 1}, True), "P")
    assert [o.id for o in result.suite_result.outcomes] == ["_structural"]
    assert result.exhausted is True


def test_a_structural_outcome_carries_a_schema_digest():
    service = ExpectationService(SUITE, repair="retry", max_iterations=1, schema=SCHEMA)
    result = service.execute(lambda p: ("text", True), "P")
    outcome = result.suite_result.outcomes[0]
    assert outcome.type == "schema"
    assert outcome.severity == "error"
    assert len(outcome.definition_hash) == 12


UNSORTABLE_SCHEMA = {
    "type": "object",
    "properties": {2024: {"type": "string"}, "name": {"type": "string"}},
}


def test_an_unsortable_schema_does_not_crash_observe_construction():
    service = ExpectationService(SUITE, repair="none", schema=UNSORTABLE_SCHEMA)
    result = service.execute(passing_llm, "P")
    assert result.suite_result.overall_pass is True


def test_an_unsortable_schema_still_digests_for_the_structural_outcome():
    service = ExpectationService(SUITE, repair="retry", max_iterations=1, schema=UNSORTABLE_SCHEMA)
    result = service.execute(lambda p: ("text", True), "P")
    outcome = result.suite_result.outcomes[0]
    assert outcome.id == "_structural"
    assert len(outcome.definition_hash) == 12


def test_a_malformed_schema_omits_field_names_from_non_record_feedback():
    # _extract_field_names raises on this shape; the gate must degrade, not crash.
    service = ExpectationService(
        SUITE, repair="retry", max_iterations=1, schema={"fields": ["name", "age"]}
    )
    result = service.execute(lambda p: ("text", True), "P")
    outcome = result.suite_result.outcomes[0]
    assert outcome.id == "_structural"
    assert "expected a JSON object" in outcome.detail


def test_observe_mode_non_record_result_fields_are_pinned():
    result = ExpectationService(SUITE, repair="none").execute(lambda p: ("text", True), "P")
    assert result.response == "text"
    assert result.executed is True
    assert result.iterations == 0
    assert result.exhausted is False


def test_a_collapse_after_a_structural_failure_keeps_the_structural_verdict():
    responses = iter([("text", True), (None, False)])
    service = ExpectationService(SUITE, repair="retry", max_iterations=3)
    result = service.execute(lambda p: next(responses), "P")
    assert result.executed is True
    assert result.response == "text"
    assert result.suite_result.outcomes[0].id == "_structural"
    assert result.exhausted is True


def test_auto_repair_hint_reaches_the_composed_prompt():
    hinted_suite = Suite(
        name="s",
        expectations=[
            {
                "id": "count",
                "type": "item_count",
                "field": "ideas",
                "params": {"min": 2},
                "hint": "brainstorm additional distinct ideas",
            }
        ],
    )
    responses = iter([{"ideas": ["a"]}, {"ideas": ["a", "b"]}])
    prompts = []

    def flaky(prompt):
        prompts.append(prompt)
        return next(responses), True

    ExpectationService(hinted_suite, repair="auto", max_iterations=2).execute(flaky, "O")
    assert "brainstorm additional distinct ideas" in prompts[1]
