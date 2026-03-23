"""Tests for WorkflowDependencyOrchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from agent_actions.workflow.parallel.dependency import WorkflowDependencyOrchestrator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workflows_root(tmp_path: Path) -> Path:
    root = tmp_path / "workflows"
    root.mkdir()
    return root


@pytest.fixture()
def mock_console() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_factory() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def orchestrator(
    workflows_root: Path, mock_console: MagicMock, mock_factory: MagicMock
) -> WorkflowDependencyOrchestrator:
    return WorkflowDependencyOrchestrator(
        workflows_root=workflows_root,
        current_workflow="current_wf",
        console=mock_console,
        workflow_factory=mock_factory,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_status_file(workflows_root: Path, workflow_name: str, status_data: dict) -> Path:
    """Write a .agent_status.json for the given workflow."""
    io_dir = workflows_root / workflow_name / "agent_io"
    io_dir.mkdir(parents=True, exist_ok=True)
    status_file = io_dir / ".agent_status.json"
    status_file.write_text(json.dumps(status_data), encoding="utf-8")
    return status_file


def _create_config_file(workflows_root: Path, workflow_name: str) -> Path:
    """Create a minimal agent_config/<name>.yml so the config-existence check passes."""
    config_dir = workflows_root / workflow_name / "agent_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / f"{workflow_name}.yml"
    config_file.write_text("# placeholder config\n", encoding="utf-8")
    return config_file


# ===========================================================================
# _check_workflow_complete
# ===========================================================================


class TestCheckWorkflowComplete:
    """Tests for the filesystem-based completion check."""

    def test_status_file_missing(self, orchestrator: WorkflowDependencyOrchestrator):
        assert orchestrator._check_workflow_complete("nonexistent_wf") is False

    def test_all_agents_completed(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        _create_status_file(
            workflows_root,
            "wf1",
            {"agent_a": {"status": "completed"}, "agent_b": {"status": "completed"}},
        )
        assert orchestrator._check_workflow_complete("wf1") is True

    def test_one_agent_not_completed(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        _create_status_file(
            workflows_root,
            "wf1",
            {"agent_a": {"status": "completed"}, "agent_b": {"status": "running"}},
        )
        assert orchestrator._check_workflow_complete("wf1") is False

    def test_malformed_json(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        io_dir = workflows_root / "wf_bad" / "agent_io"
        io_dir.mkdir(parents=True)
        (io_dir / ".agent_status.json").write_text("{not valid json", encoding="utf-8")
        assert orchestrator._check_workflow_complete("wf_bad") is False

    def test_empty_status_dict(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        _create_status_file(workflows_root, "wf_empty", {})
        # all() on an empty iterable returns True
        assert orchestrator._check_workflow_complete("wf_empty") is True

    def test_os_error_reading_status_file(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        _create_status_file(workflows_root, "wf_oserr", {"a": {"status": "completed"}})
        with patch("builtins.open", side_effect=OSError("permission denied")):
            assert orchestrator._check_workflow_complete("wf_oserr") is False


# ===========================================================================
# resolve_upstream_workflows
# ===========================================================================


class TestResolveUpstreamWorkflows:
    """Tests for upstream dependency resolution."""

    def test_no_dependencies(self, orchestrator: WorkflowDependencyOrchestrator):
        configs = {"agent1": {"some_key": "val"}}
        result = orchestrator.resolve_upstream_workflows(configs, None, None, False)
        assert result is True
        orchestrator.workflow_factory.assert_not_called()

    def test_single_upstream_runs_successfully(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "upstream_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf

        configs = {"agent1": {"dependencies": [{"workflow": "upstream_wf"}]}}
        result = orchestrator.resolve_upstream_workflows(configs, "/code", "/def", True)

        assert result is True
        mock_factory.assert_called_once()
        call_kwargs = mock_factory.call_args.kwargs
        assert "upstream_wf" in call_kwargs["config_path"]
        assert call_kwargs["run_upstream"] is False
        assert call_kwargs["run_downstream"] is False

    def test_single_upstream_links_artifacts(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "upstream_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf
        orchestrator.artifact_linker = MagicMock()

        configs = {"agent1": {"dependencies": [{"workflow": "upstream_wf"}]}}
        orchestrator.resolve_upstream_workflows(configs, None, None, False)

        orchestrator.artifact_linker.link_upstream_artifacts.assert_called_once_with(
            "upstream_wf", "current_wf"
        )

    def test_upstream_already_completed_skips_execution(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "done_wf")
        _create_status_file(workflows_root, "done_wf", {"a": {"status": "completed"}})

        configs = {"agent1": {"dependencies": [{"workflow": "done_wf"}]}}
        result = orchestrator.resolve_upstream_workflows(configs, None, None, False)

        assert result is True
        # Factory should NOT be called since workflow is already complete
        mock_factory.assert_not_called()

    def test_upstream_already_completed_still_links_artifacts(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
    ):
        _create_config_file(workflows_root, "done_wf")
        _create_status_file(workflows_root, "done_wf", {"a": {"status": "completed"}})
        orchestrator.artifact_linker = MagicMock()

        configs = {"agent1": {"dependencies": [{"workflow": "done_wf"}]}}
        orchestrator.resolve_upstream_workflows(configs, None, None, False)

        orchestrator.artifact_linker.link_upstream_artifacts.assert_called_once_with(
            "done_wf", "current_wf"
        )

    def test_upstream_batch_pending_returns_false(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "pending_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = None
        mock_factory.return_value = mock_wf

        configs = {"agent1": {"dependencies": [{"workflow": "pending_wf"}]}}
        result = orchestrator.resolve_upstream_workflows(configs, None, None, False)

        assert result is False

    def test_upstream_config_missing_raises_runtime_error(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
    ):
        configs = {"agent1": {"dependencies": [{"workflow": "missing_wf"}]}}
        with pytest.raises(RuntimeError, match="Recursive execution failed"):
            orchestrator.resolve_upstream_workflows(configs, None, None, False)

    def test_duplicate_upstream_processed_once(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "shared_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf

        configs = {
            "agent1": {"dependencies": [{"workflow": "shared_wf"}]},
            "agent2": {"dependencies": [{"workflow": "shared_wf"}]},
        }
        result = orchestrator.resolve_upstream_workflows(configs, None, None, False)

        assert result is True
        assert mock_factory.call_count == 1

    def test_non_workflow_dependencies_skipped(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        mock_factory: MagicMock,
    ):
        configs = {
            "agent1": {
                "dependencies": [
                    {"file": "data.csv"},
                    "some_string_dep",
                ]
            }
        }
        result = orchestrator.resolve_upstream_workflows(configs, None, None, False)
        assert result is True
        mock_factory.assert_not_called()

    def test_upstream_execution_raises_wraps_in_runtime_error(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "fail_wf")
        mock_wf = MagicMock()
        mock_wf.run.side_effect = ValueError("boom")
        mock_factory.return_value = mock_wf

        configs = {"agent1": {"dependencies": [{"workflow": "fail_wf"}]}}
        with pytest.raises(
            RuntimeError, match=r"Recursive execution failed.*ValueError.*boom"
        ):
            orchestrator.resolve_upstream_workflows(configs, None, None, False)


# ===========================================================================
# resolve_downstream_workflows
# ===========================================================================


class TestResolveDownstreamWorkflows:
    """Tests for downstream dependency resolution."""

    def test_no_downstream_workflows(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        mock_console: MagicMock,
    ):
        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.return_value = []
            mock_idx_prop.return_value = mock_idx

            result = orchestrator.resolve_downstream_workflows(None, None, False)

        assert result is True
        # Verify "no downstream" message was printed
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "No downstream" in printed or "no downstream" in printed.lower()

    def test_single_downstream_runs_successfully(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "down_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf

        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.return_value = ["down_wf"]
            mock_idx_prop.return_value = mock_idx

            result = orchestrator.resolve_downstream_workflows("/code", "/def", True)

        assert result is True
        mock_factory.assert_called_once()
        call_kwargs = mock_factory.call_args.kwargs
        assert "down_wf" in call_kwargs["config_path"]

    def test_downstream_batch_pending_returns_false(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "pend_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = None
        mock_factory.return_value = mock_wf

        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.return_value = ["pend_wf"]
            mock_idx_prop.return_value = mock_idx

            result = orchestrator.resolve_downstream_workflows(None, None, False)

        assert result is False

    def test_downstream_config_missing_raises(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
    ):
        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.return_value = ["no_config_wf"]
            mock_idx_prop.return_value = mock_idx

            with pytest.raises(FileNotFoundError):
                orchestrator.resolve_downstream_workflows(None, None, False)

    def test_multiple_downstream_execute_in_order_and_stop_on_pending(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "ds_a")
        _create_config_file(workflows_root, "ds_b")
        _create_config_file(workflows_root, "ds_c")

        mock_wf_ok = MagicMock()
        mock_wf_ok.run.return_value = True
        mock_wf_pending = MagicMock()
        mock_wf_pending.run.return_value = None
        # ds_a succeeds, ds_b returns None (pending) → ds_c never called
        mock_factory.side_effect = [mock_wf_ok, mock_wf_pending]

        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.return_value = ["ds_a", "ds_b", "ds_c"]
            mock_idx_prop.return_value = mock_idx

            result = orchestrator.resolve_downstream_workflows(None, None, False)

        assert result is False
        # Factory called for ds_a and ds_b, but not ds_c
        assert mock_factory.call_count == 2
        first_config = mock_factory.call_args_list[0].kwargs["config_path"]
        second_config = mock_factory.call_args_list[1].kwargs["config_path"]
        assert "ds_a" in first_config
        assert "ds_b" in second_config

    def test_topological_sort_raises_propagates(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
    ):
        with patch.object(
            type(orchestrator),
            "workspace_index",
            new_callable=PropertyMock,
        ) as mock_idx_prop:
            mock_idx = MagicMock()
            mock_idx.topological_sort_downstream.side_effect = ValueError("cycle")
            mock_idx_prop.return_value = mock_idx

            with pytest.raises(ValueError, match="cycle"):
                orchestrator.resolve_downstream_workflows(None, None, False)


# ===========================================================================
# _execute_downstream_workflow
# ===========================================================================


class TestExecuteDownstreamWorkflow:
    """Tests for single downstream workflow execution."""

    def test_happy_path(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "ds_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf

        result = orchestrator._execute_downstream_workflow("ds_wf", None, None, False)
        assert result is True

    def test_happy_path_links_artifacts(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "ds_wf")
        mock_wf = MagicMock()
        mock_wf.run.return_value = True
        mock_factory.return_value = mock_wf
        orchestrator.artifact_linker = MagicMock()

        orchestrator._execute_downstream_workflow("ds_wf", None, None, False)

        orchestrator.artifact_linker.link_downstream_artifacts.assert_called_once_with(
            "current_wf", "ds_wf"
        )

    def test_batch_pending_returns_none(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        workflows_root: Path,
        mock_factory: MagicMock,
    ):
        _create_config_file(workflows_root, "ds_pend")
        mock_wf = MagicMock()
        mock_wf.run.return_value = None
        mock_factory.return_value = mock_wf

        result = orchestrator._execute_downstream_workflow("ds_pend", None, None, False)
        assert result is None


# ===========================================================================
# workspace_index property
# ===========================================================================


class TestWorkspaceIndexProperty:
    """Tests for lazy-loaded workspace index."""

    def test_first_access_creates_and_scans(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
    ):
        with patch("agent_actions.workflow.parallel.dependency.WorkspaceIndex") as MockWSI:
            mock_instance = MagicMock()
            MockWSI.return_value = mock_instance

            idx = orchestrator.workspace_index

            MockWSI.assert_called_once_with(orchestrator.workflows_root)
            mock_instance.scan_workspace.assert_called_once()
            assert idx is mock_instance

    def test_subsequent_access_returns_cached(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
    ):
        with patch("agent_actions.workflow.parallel.dependency.WorkspaceIndex") as MockWSI:
            mock_instance = MagicMock()
            MockWSI.return_value = mock_instance

            first = orchestrator.workspace_index
            second = orchestrator.workspace_index

            # Only constructed once
            assert MockWSI.call_count == 1
            assert first is second


# ===========================================================================
# _print_batch_pending_message
# ===========================================================================


class TestPrintBatchPendingMessage:
    """Tests for batch-pending console messages."""

    def test_upstream_message_includes_upstream_flag(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        mock_console: MagicMock,
    ):
        orchestrator._print_batch_pending_message("up_wf", is_upstream=True)

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "--upstream" in printed
        assert "Upstream" in printed

    def test_downstream_message_includes_downstream_flag(
        self,
        orchestrator: WorkflowDependencyOrchestrator,
        mock_console: MagicMock,
    ):
        orchestrator._print_batch_pending_message("down_wf", is_upstream=False)

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "--downstream" in printed
        assert "Downstream" in printed
