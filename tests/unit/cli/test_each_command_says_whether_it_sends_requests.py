"""Each command that loads a workflow says whether it will send requests to a model."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.args import RetryCommandArgs, RunCommandArgs
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


class _StopAtLoad(Exception):
    pass


def _sends_requests(module: str, command, tmp_path) -> bool:
    with (
        patch(f"agent_actions.cli.{module}.load_workflow", side_effect=_StopAtLoad) as load,
        patch(f"agent_actions.cli.{module}.ProjectPathsFactory") as paths,
        patch(f"agent_actions.cli.{module}.get_storage_backend", create=True),
        patch(f"agent_actions.cli.{module}.PromptValidator", create=True),
        patch(f"agent_actions.cli.{module}._read_manifest", return_value=None, create=True),
    ):
        paths.create_project_paths.return_value = MagicMock()
        with pytest.raises(_StopAtLoad):
            command.execute(project_root=tmp_path)
    return load.call_args.kwargs["sends_requests"]


def test_run_sends_requests(tmp_path):
    from agent_actions.cli.run import RunCommand

    assert _sends_requests("run", RunCommand(RunCommandArgs(agent="wf")), tmp_path) is True


@pytest.mark.parametrize("dry_run", [False, True], ids=["retry", "dry-run"])
def test_retry_sends_requests_unless_it_is_a_dry_run(tmp_path, dry_run):
    from agent_actions.cli.retry import RetryCommand

    command = RetryCommand(RetryCommandArgs(agent="wf", dry_run=dry_run))

    assert _sends_requests("retry", command, tmp_path) is (not dry_run)


def test_schema_sends_none(tmp_path):
    from agent_actions.cli.schema import SchemaCommand

    command = SchemaCommand(agent="wf", user_code=None, json_output=False, verbose=False)

    assert _sends_requests("schema", command, tmp_path) is False


def test_dispositions_sends_none(tmp_path):
    from agent_actions.cli.dispositions import DispositionsCommand

    command = DispositionsCommand(agent="wf", action=None, quarantined=False)

    assert _sends_requests("dispositions", command, tmp_path) is False


@pytest.mark.parametrize("dry_run", [False, True], ids=["filter", "dry-run"])
def test_retry_filter_sends_none(tmp_path, dry_run):
    from agent_actions.cli.retry_filter import RetryFilterCommand

    command = RetryFilterCommand(RetryCommandArgs(agent="wf", dry_run=dry_run))

    assert _sends_requests("retry_filter", command, tmp_path) is False


def test_the_inspector_sends_none(tmp_path):
    from agent_actions.services.workflow_inspector import WorkflowInspector

    inspector = WorkflowInspector.__new__(WorkflowInspector)
    inspector.agent_name = "wf"
    inspector.action_configs = {}
    inspector.project_root = tmp_path
    inspector._config_path = tmp_path / "wf.yml"
    with (
        patch.object(WorkflowInspector, "load"),
        patch("agent_actions.services.workflow_inspector.PreflightService") as preflight,
        patch("agent_actions.services.workflow_inspector.strip_unreachable_drops"),
    ):
        inspector.validate()

    assert preflight.call_args.kwargs["sends_requests"] is False


def _resolve(actions: dict, sends_requests: bool):
    return WorkflowResolutionService(
        action_configs=actions, sends_requests=sends_requests
    ).resolve_all()


@pytest.fixture
def _no_shared_key(monkeypatch):
    monkeypatch.delenv("SHARED_KEY", raising=False)
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)


@pytest.mark.usefixtures("_no_shared_key")
class TestOneWarningPerUnsetVariable:
    def test_actions_reading_one_variable_share_one_warning(self):
        actions = {
            name: {"model_vendor": "openai", "api_key": "SHARED_KEY"}
            for name in ("a1", "a2", "a3", "a4")
        }

        result = _resolve(actions, sends_requests=False)

        assert result.errors == []
        assert [(w.message, w.hint) for w in result.warnings] == [
            (
                "API key environment variable 'SHARED_KEY' is not set "
                "(required by 4 actions: a1, a2, a3, ...; vendor(s) 'openai'); "
                "connection check skipped",
                "Set the environment variable: export SHARED_KEY=...",
            )
        ]

    def test_two_vendors_sharing_one_variable_are_both_named_sorted(self):
        actions = {
            "draft": {"model_vendor": "openai", "api_key": "SHARED_KEY"},
            "check": {"model_vendor": "groq", "api_key": "SHARED_KEY"},
        }

        result = _resolve(actions, sends_requests=False)

        assert [w.message for w in result.warnings] == [
            "API key environment variable 'SHARED_KEY' is not set "
            "(required by 2 actions: draft, check; vendor(s) 'groq', 'openai'); "
            "connection check skipped"
        ]

    def test_a_run_keeps_one_error_per_action(self):
        actions = {
            "draft": {"model_vendor": "openai", "api_key": "SHARED_KEY"},
            "check": {"model_vendor": "groq", "api_key": "SHARED_KEY"},
        }

        result = _resolve(actions, sends_requests=True)

        assert result.warnings == []
        assert [e.message for e in result.errors] == [
            "API key environment variable 'SHARED_KEY' is not set "
            "(required by action 'draft', vendor 'openai')",
            "API key environment variable 'SHARED_KEY' is not set "
            "(required by action 'check', vendor 'groq')",
        ]
