"""Tests for the execution summary renderer."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock

from rich.console import Console

from agent_actions.cli.renderers.execution_renderer import (
    ActionResult,
    ExecutionRenderer,
    WorkflowExecutionSnapshot,
    build_execution_snapshot,
)


def _capture_render(snapshot: WorkflowExecutionSnapshot) -> str:
    """Render a snapshot and return the captured output."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80, color_system="truecolor")
    ExecutionRenderer(console).render(snapshot)
    return buf.getvalue()


def _basic_snapshot(**overrides) -> WorkflowExecutionSnapshot:
    """Build a minimal snapshot with sensible defaults."""
    defaults = {
        "workflow_name": "test_workflow",
        "workflow_version": "1.0",
        "execution_levels": [["action_a"], ["action_b"]],
        "action_results": {
            "action_a": ActionResult(
                name="action_a",
                kind="llm",
                status="completed",
                execution_time=1.2,
                model_vendor="openai",
                model_name="gpt-4o-mini",
            ),
            "action_b": ActionResult(
                name="action_b",
                kind="tool",
                status="completed",
                execution_time=0.1,
            ),
        },
        "total_elapsed": 1.3,
    }
    defaults.update(overrides)
    return WorkflowExecutionSnapshot(**defaults)


class TestExecutionRenderer:
    def test_renders_header_with_name_and_version(self):
        output = _capture_render(_basic_snapshot())
        assert "test_workflow" in output
        assert "v1.0" in output

    def test_renders_action_count_stats(self):
        output = _capture_render(_basic_snapshot())
        assert "2 actions" in output

    def test_renders_kind_badges(self):
        output = _capture_render(_basic_snapshot())
        assert "llm" in output
        assert "tool" in output

    def test_renders_status_icons(self):
        output = _capture_render(_basic_snapshot())
        assert "✓" in output

    def test_renders_latency(self):
        output = _capture_render(_basic_snapshot())
        assert "1.2s" in output
        assert "0.1s" in output

    def test_renders_provider_info(self):
        output = _capture_render(_basic_snapshot())
        assert "opena" in output  # truncated to 5 chars
        assert "gpt-4o-mini" in output

    def test_renders_failed_actions(self):
        snap = _basic_snapshot(
            action_results={
                "broken": ActionResult(
                    name="broken",
                    kind="llm",
                    status="failed",
                    error_message="API timeout after 30s",
                ),
            },
            execution_levels=[["broken"]],
        )
        output = _capture_render(snap)
        assert "✗" in output
        assert "1 failed" in output
        assert "API timeout" in output

    def test_renders_skipped_actions(self):
        snap = _basic_snapshot(
            action_results={
                "guarded": ActionResult(
                    name="guarded",
                    kind="tool",
                    status="skipped",
                    skip_reason="guard condition not met",
                ),
            },
            execution_levels=[["guarded"]],
        )
        output = _capture_render(snap)
        assert "○" in output
        assert "skipped" in output

    def test_renders_parallel_level_with_box(self):
        snap = _basic_snapshot(
            execution_levels=[["a", "b"]],
            action_results={
                "a": ActionResult(name="a", kind="llm", status="completed", execution_time=1.0),
                "b": ActionResult(name="b", kind="tool", status="completed", execution_time=0.5),
            },
        )
        output = _capture_render(snap)
        # Should contain box-drawing characters for parallel grouping
        assert "┌" in output
        assert "└" in output

    def test_renders_done_footer(self):
        output = _capture_render(_basic_snapshot())
        assert "Done in" in output

    def test_empty_version_omitted(self):
        snap = _basic_snapshot(workflow_version="")
        output = _capture_render(snap)
        assert "  v" not in output

    def test_long_action_name_truncated(self):
        long_name = "a" * 40
        snap = _basic_snapshot(
            execution_levels=[[long_name]],
            action_results={
                long_name: ActionResult(name=long_name, kind="llm", status="completed"),
            },
        )
        output = _capture_render(snap)
        assert "..." in output


def _mock_workflow(action_configs, status_details=None, levels=None, version=""):
    """Build a mock workflow object for build_execution_snapshot tests."""
    from agent_actions.workflow.managers.state import ActionStatus

    state_mgr = MagicMock()

    def _get_details(name):
        if status_details and name in status_details:
            return status_details[name]
        return {"status": ActionStatus.PENDING}

    state_mgr.get_status_details = _get_details

    orchestrator = MagicMock()
    orchestrator.compute_execution_levels.return_value = levels or [list(action_configs.keys())]

    core = SimpleNamespace(state_manager=state_mgr, action_level_orchestrator=orchestrator)
    services = SimpleNamespace(core=core)

    manager = SimpleNamespace(user_config={"version": version} if version else {})
    config = SimpleNamespace(manager=manager)
    metadata = SimpleNamespace(
        agent_name="test_wf",
        action_configs=action_configs,
    )

    return SimpleNamespace(
        action_configs=action_configs,
        agent_name="test_wf",
        services=services,
        config=config,
        metadata=metadata,
    )


class TestBuildExecutionSnapshot:
    def test_reads_kind_from_config(self):
        wf = _mock_workflow({"act_a": {"kind": "tool", "model_vendor": "", "model_name": ""}})
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.action_results["act_a"].kind == "tool"

    def test_defaults_kind_to_llm(self):
        wf = _mock_workflow({"act_a": {"model_vendor": "openai", "model_name": "gpt-4o"}})
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.action_results["act_a"].kind == "llm"

    def test_extracts_execution_time(self):
        from agent_actions.workflow.managers.state import ActionStatus

        wf = _mock_workflow(
            {"act_a": {"kind": "llm"}},
            status_details={
                "act_a": {"status": ActionStatus.COMPLETED, "execution_time": 2.5},
            },
        )
        snap = build_execution_snapshot(wf, 3.0)
        assert snap.action_results["act_a"].execution_time == 2.5

    def test_extracts_error_message(self):
        from agent_actions.workflow.managers.state import ActionStatus

        wf = _mock_workflow(
            {"act_a": {"kind": "llm"}},
            status_details={
                "act_a": {
                    "status": ActionStatus.FAILED,
                    "error_message": "API rate limit",
                },
            },
        )
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.action_results["act_a"].error_message == "API rate limit"

    def test_extracts_skip_reason(self):
        from agent_actions.workflow.managers.state import ActionStatus

        wf = _mock_workflow(
            {"act_a": {"kind": "tool"}},
            status_details={
                "act_a": {
                    "status": ActionStatus.SKIPPED,
                    "skip_reason": "upstream failed",
                },
            },
        )
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.action_results["act_a"].skip_reason == "upstream failed"

    def test_reads_version_from_config(self):
        wf = _mock_workflow({"a": {"kind": "llm"}}, version="2.1")
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.workflow_version == "2.1"

    def test_handles_enum_status(self):
        from agent_actions.workflow.managers.state import ActionStatus

        wf = _mock_workflow(
            {"a": {"kind": "llm"}},
            status_details={"a": {"status": ActionStatus.COMPLETED}},
        )
        snap = build_execution_snapshot(wf, 1.0)
        assert snap.action_results["a"].status == "completed"
