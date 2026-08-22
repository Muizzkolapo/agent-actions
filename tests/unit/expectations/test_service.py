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
                "rule": "r",
                "context": ["extract_context.source_context"],
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
    judge_inline = [{"id": "on_topic", "type": "llm_judge", "field": "ideas", "rule": "on topic"}]
    service = create_expectation_service_from_config(
        {"expectations": judge_inline, "repair": "none"},
        action_name="brainstorm",
        agent_config={"model_vendor": "anthropic", "model_name": "claude-sonnet-5"},
    )
    assert service._judge is not None


def test_factory_judge_dispatcher_calls_through_to_invoke_judge_with_votes():
    judge_inline = [{"id": "on_topic", "type": "llm_judge", "field": "ideas", "rule": "on topic"}]
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
    judge_inline = [{"id": "on_topic", "type": "llm_judge", "field": "ideas", "rule": "on topic"}]
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


def test_factory_judge_dispatcher_survives_a_network_error_without_crashing_the_record():
    judge_inline = [{"id": "on_topic", "type": "llm_judge", "field": "ideas", "rule": "on topic"}]
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
