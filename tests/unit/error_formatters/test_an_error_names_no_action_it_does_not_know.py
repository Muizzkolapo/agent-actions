"""An error prints as the action only an action it names, and its context stays apart from its Problem."""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError, ConfigValidationError, enrich_exception_context
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.logging.errors import format_user_error
from agent_actions.logging.errors.translator import ErrorTranslator
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.services.preflight_service import PreflightService
from agent_actions.utils.udf_management.registry import clear_registry, record_skipped_tool_files

WORKFLOW = "my_workflow"
CLI_CONTEXT = {"command": "run", "agent": WORKFLOW}
BATCH_MESSAGE = "Missing required field 'model_vendor' for batch processing."


def _raised(fn) -> Exception:
    with pytest.raises(Exception) as exc_info:
        fn()
    return exc_info.value


def _lines(error: Exception, context: dict | None = None) -> list[str]:
    return format_user_error(error, context).splitlines()


def _action_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("  Action:")]


def _batch_submission_error(agent_config: dict) -> Exception:
    service = BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        registry_manager_factory=MagicMock(),
    )
    return _raised(
        lambda: service._submit_to_provider(
            agent_config=agent_config,
            batch_name="b",
            tasks=[{"id": "1"}],
            output_directory=None,
            action_name="label_rows",
        )
    )


def _template_error_of_a_nameless_action() -> Exception:
    return _raised(
        lambda: PromptPreparationService._render_prompt_template("{{ source.text ", {"source": {}})
    )


class TestAMissingFieldErrorThatNamesNoAction:
    def test_the_cli_workflow_is_the_agent_and_never_the_action(self):
        error = ConfigValidationError("model_vendor", BATCH_MESSAGE)
        output = format_user_error(error, CLI_CONTEXT)
        lines = output.splitlines()

        assert lines[0] == "Configuration Error: Missing required configuration fields"
        assert f"  Agent: {WORKFLOW}" in lines
        assert _action_lines(lines) == []
        assert f"- name: {WORKFLOW}" not in output
        assert "- name: <action name>" in output

    def test_the_problem_is_the_errors_own_words_when_it_lists_no_field(self):
        error = ConfigValidationError("model_vendor", BATCH_MESSAGE)
        problem = next(line for line in _lines(error) if line.startswith("  Problem:"))

        assert BATCH_MESSAGE in problem
        assert "missing required configuration: " not in problem


def test_a_batch_submission_with_no_vendor_names_its_action_and_the_field():
    lines = _lines(_batch_submission_error({}), CLI_CONTEXT)

    assert f"  Agent: {WORKFLOW}" in lines
    assert "  Action: label_rows" in lines
    assert "  Problem: The action is missing required configuration: 'model_vendor'" in lines


class TestAnAgentNameIsNeverTheAction:
    def test_on_a_template_error(self):
        error = _template_error_of_a_nameless_action()
        enrich_exception_context(error, agent_name=WORKFLOW)
        lines = _lines(error, CLI_CONTEXT)

        assert f"  Agent: {WORKFLOW}" in lines
        assert _action_lines(lines) == []

    def test_on_a_missing_field_error(self):
        error = ConfigValidationError(
            "model_vendor",
            BATCH_MESSAGE,
            context={"agent_name": WORKFLOW, "missing_fields": ["model_vendor"]},
        )
        lines = _lines(error)

        assert "  Problem: The action is missing required configuration: 'model_vendor'" in lines
        assert _action_lines(lines) == []


class TestABlankActionPrintsNoActionLine:
    def test_a_template_error_of_a_nameless_action(self):
        error = _template_error_of_a_nameless_action()
        lines = _lines(error, CLI_CONTEXT)

        assert error.context["action_name"] == ""
        assert f"  Agent: {WORKFLOW}" in lines
        assert _action_lines(lines) == []
        assert ErrorTranslator().translate(error, CLI_CONTEXT).context["agent"] == WORKFLOW
        assert "action_name" not in ErrorTranslator().translate(error, CLI_CONTEXT).context

    def test_an_error_whose_formatter_passes_its_context_through(self):
        error = ConfigurationError("Invalid thing", context={"action_name": " ", "agent": WORKFLOW})
        lines = _lines(error)

        assert f"  Agent: {WORKFLOW}" in lines
        assert _action_lines(lines) == []


@pytest.fixture
def _skipped_tool_file():
    clear_registry()
    record_skipped_tool_files({"tools/broken.py": "boom at import"})
    yield
    clear_registry()


@pytest.mark.usefixtures("_skipped_tool_file")
def test_the_context_lines_stand_apart_from_the_skipped_tool_files():
    configs = {"fetch_rows": {"kind": "tool", "model_name": "no_such_probe_fn"}}
    error = _raised(lambda: PreflightService(WORKFLOW, configs, None, "w.yml").validate())
    lines = _lines(error)

    skipped = lines.index("  tools/broken.py: boom at import")
    agent = lines.index(f"  Agent: {WORKFLOW}")
    assert lines[skipped + 1 : agent] == [""]
    assert lines[agent + 1] == "  Action: fetch_rows"
