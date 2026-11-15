"""An error raised while an action runs names the action as the action, never as the agent."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError, ConfigValidationError, ProcessingError
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.logging.errors import format_user_error
from agent_actions.output.response.expander_validation import validate_action_name
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.workflow.managers.loop import VersionOutputCorrelator

WORKFLOW = "my_workflow"
CLI_CONTEXT = {"command": "run", "agent": WORKFLOW}


def _api_key_error(monkeypatch, case: str) -> ConfigurationError:
    monkeypatch.delenv("PROBE_UNSET_KEY", raising=False)
    monkeypatch.setenv("PROBE_EMPTY_KEY", "")
    configs = {
        "missing": {"agent_type": "summarize_doc"},
        "unset": {"agent_type": "summarize_doc", "api_key": "${PROBE_UNSET_KEY}"},
        "empty": {"agent_type": "summarize_doc", "api_key": "${PROBE_EMPTY_KEY}"},
    }
    with pytest.raises(ConfigurationError) as exc_info:
        BaseClient.get_api_key(configs[case])
    return exc_info.value


def _version_correlation_error() -> ConfigurationError:
    backend = MagicMock()
    backend.list_target_files.side_effect = sqlite3.OperationalError("database is locked")
    correlator = VersionOutputCorrelator(Path("/tmp/agent_io"), storage_backend=backend)
    with pytest.raises(ConfigurationError) as exc_info:
        correlator.prepare_correlated_input("merge_answers", ["answer_1", "answer_2"], 0)
    return exc_info.value


def _error(monkeypatch, case: str) -> tuple[str, ConfigurationError]:
    if case == "version_correlation":
        return "merge_answers", _version_correlation_error()
    return "summarize_doc", _api_key_error(monkeypatch, case)


CASES = ["missing", "unset", "empty", "version_correlation"]


@pytest.mark.parametrize("case", CASES)
def test_the_action_is_named_as_the_action_not_as_the_agent(monkeypatch, case):
    action, error = _error(monkeypatch, case)
    lines = format_user_error(error).splitlines()

    assert error.context["action_name"] == action
    assert "agent" not in error.context
    assert f"  Action: {action}" in lines
    assert f"  Agent: {action}" not in lines
    assert not any(f"agent '{action}'" in line for line in lines)


@pytest.mark.parametrize("case", CASES)
def test_the_cli_workflow_is_the_agent_and_the_action_stays_named(monkeypatch, case):
    action, error = _error(monkeypatch, case)
    lines = format_user_error(error, CLI_CONTEXT).splitlines()

    assert f"  Agent: {WORKFLOW}" in lines
    assert f"  Action: {action}" in lines


def test_an_error_that_is_not_a_configuration_error_names_its_action():
    backend = MagicMock()
    backend.load_metadata.return_value = None
    with pytest.raises(ProcessingError) as exc_info:
        BatchContextManager.load_batch_context_map(backend, "label_rows", "batch_1")
    lines = format_user_error(exc_info.value).splitlines()

    assert not lines[0].startswith("Configuration Error")
    assert "  Action: label_rows" in lines


def _nameless_action_error(case: str) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as exc_info:
        if case == "name_none":
            validate_action_name(None)
        else:
            ConfigRenderingService()._validate_entry_with_pydantic(
                {"model_vendor": "openai"}, "w", "action_configuration"
            )
    return exc_info.value


@pytest.mark.parametrize("case", ["name_none", "entry_without_name"])
def test_an_error_about_an_action_with_no_name_prints_no_action_line(case):
    error = _nameless_action_error(case)
    lines = format_user_error(error).splitlines()

    assert error.context.get("action_name") is None
    assert not any(line.startswith("  Action:") for line in lines)
