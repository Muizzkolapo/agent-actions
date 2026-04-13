"""Tests for RunCommand.execute() — project_root wiring and status messages."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.run import RunCommand
from agent_actions.utils.path_utils import get_path_manager, reset_path_manager
from agent_actions.validation.run_validator import RunCommandArgs


def _make_args(**overrides) -> RunCommandArgs:
    defaults = {
        "agent": "my_agent.yml",
        "user_code": None,
        "use_tools": False,
        "execution_mode": "auto",
        "concurrency_limit": 5,
        "fresh": False,
    }
    defaults.update(overrides)
    return RunCommandArgs(**defaults)


class TestRunCommandProjectRootWiring:
    """RunCommand.execute() installs a scoped PathManager when project_root is given."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Ensure set_path_manager mutations don't leak between tests."""
        reset_path_manager()
        yield
        reset_path_manager()

    def test_execute_sets_path_manager_with_project_root(self, tmp_path):
        """When project_root is provided, the global PathManager is set with that root."""
        cmd = RunCommand(_make_args())

        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as mock_paths,
            patch("agent_actions.cli.run.find_config_file", return_value=tmp_path / "cfg.yml"),
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.ConfigRenderingService.render_and_load_config"),
            patch("agent_actions.cli.run.AgentWorkflow") as mock_wf,
            patch("agent_actions.cli.run.RunTracker") as mock_tracker,
            patch.object(cmd, "_run_workflow_execution"),
        ):
            mock_paths.return_value = MagicMock(
                prompt_dir=tmp_path,
                agent_config_dir=tmp_path,
                template_dir=tmp_path,
                rendered_workflows_dir=tmp_path,
                default_config_path=tmp_path / "default.yml",
                io_dir=tmp_path,
            )
            mock_wf_instance = MagicMock()
            mock_wf_instance.execution_order = ["a1"]
            mock_wf_instance.action_configs = {"a1": {}}
            mock_wf.return_value = mock_wf_instance
            mock_tracker_instance = MagicMock()
            mock_tracker_instance.start_workflow_run.return_value = "run-123"
            mock_tracker.return_value = mock_tracker_instance

            cmd.execute(project_root=tmp_path)

        pm = get_path_manager()
        assert pm._project_root == tmp_path.resolve()

    def test_execute_without_project_root_skips_set_path_manager(self, tmp_path):
        """When project_root is None, set_path_manager is not called."""
        cmd = RunCommand(_make_args())

        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as mock_paths,
            patch("agent_actions.cli.run.find_config_file", return_value=tmp_path / "cfg.yml"),
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.ConfigRenderingService.render_and_load_config"),
            patch("agent_actions.cli.run.AgentWorkflow") as mock_wf,
            patch("agent_actions.cli.run.RunTracker") as mock_tracker,
            patch.object(cmd, "_run_workflow_execution"),
            patch("agent_actions.utils.path_utils.set_path_manager") as mock_set_pm,
        ):
            mock_paths.return_value = MagicMock(
                prompt_dir=tmp_path,
                agent_config_dir=tmp_path,
                template_dir=tmp_path,
                rendered_workflows_dir=tmp_path,
                default_config_path=tmp_path / "default.yml",
                io_dir=tmp_path,
            )
            mock_wf_instance = MagicMock()
            mock_wf_instance.execution_order = ["a1"]
            mock_wf_instance.action_configs = {"a1": {}}
            mock_wf.return_value = mock_wf_instance
            mock_tracker_instance = MagicMock()
            mock_tracker_instance.start_workflow_run.return_value = "run-123"
            mock_tracker.return_value = mock_tracker_instance

            cmd.execute(project_root=None)

        mock_set_pm.assert_not_called()


# ---------------------------------------------------------------------------
# Status message tests (issue #81)
# ---------------------------------------------------------------------------


def _build_workflow_mock(tmp_path, state_overrides=None):
    """Build a mock AgentWorkflow with configurable state manager behaviour."""
    wf = MagicMock()
    wf.execution_order = ["action_a", "action_b", "action_c"]

    sm = wf.services.core.state_manager
    sm.is_workflow_complete.return_value = False
    sm.is_workflow_done.return_value = False
    sm.has_any_failed.return_value = False
    sm.get_failed_actions.return_value = []
    sm.get_skipped_actions.return_value = []
    sm.get_batch_submitted_actions.return_value = []
    sm.get_summary.return_value = {"pending": 1}

    if state_overrides:
        for attr, value in state_overrides.items():
            getattr(sm, attr).return_value = value

    return wf


class TestRunCommandStatusMessages:
    """Post-execution status determination emits accurate messages (issue #81)."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        reset_path_manager()
        yield
        reset_path_manager()

    def _execute(self, tmp_path, state_overrides):
        """Run execute() with a mocked workflow. Returns the tracker mock."""
        cmd = RunCommand(_make_args())
        wf_mock = _build_workflow_mock(tmp_path, state_overrides)

        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as mock_paths,
            patch("agent_actions.cli.run.find_config_file", return_value=tmp_path / "cfg.yml"),
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.ConfigRenderingService.render_and_load_config"),
            patch("agent_actions.cli.run.AgentWorkflow", return_value=wf_mock),
            patch("agent_actions.cli.run.RunTracker") as mock_tracker,
            patch.object(cmd, "_run_workflow_execution"),
        ):
            mock_paths.return_value = MagicMock(
                prompt_dir=tmp_path,
                agent_config_dir=tmp_path,
                template_dir=tmp_path,
                rendered_workflows_dir=tmp_path,
                default_config_path=tmp_path / "default.yml",
                io_dir=tmp_path,
            )
            tracker_inst = MagicMock()
            tracker_inst.start_workflow_run.return_value = "run-123"
            mock_tracker.return_value = tracker_inst

            cmd.execute(project_root=tmp_path)

            return tracker_inst

    # -- SUCCESS paths -------------------------------------------------------

    def test_all_completed_shows_success(self, tmp_path, capsys):
        tracker = self._execute(tmp_path, {"is_workflow_complete": True})
        capsys.readouterr()  # consume output
        assert tracker.finalize_workflow_run.call_args[1]["status"] == "SUCCESS"

    def test_done_all_skipped_none_failed_shows_success(self, tmp_path, capsys):
        """All terminal, none failed (some skipped by guards) → SUCCESS."""
        tracker = self._execute(
            tmp_path,
            {"is_workflow_complete": False, "is_workflow_done": True, "has_any_failed": False},
        )
        out = capsys.readouterr().out
        assert "batch" not in out.lower()
        assert "paused" not in out.lower()
        assert tracker.finalize_workflow_run.call_args[1]["status"] == "SUCCESS"

    # -- FAILED paths --------------------------------------------------------

    def test_failed_with_skipped_lists_both(self, tmp_path, capsys):
        """Failed + skipped actions listed, exits non-zero."""
        with pytest.raises(SystemExit) as exc_info:
            self._execute(
                tmp_path,
                {
                    "is_workflow_complete": False,
                    "is_workflow_done": True,
                    "has_any_failed": True,
                    "get_failed_actions": ["action_a"],
                    "get_skipped_actions": ["action_b", "action_c"],
                },
            )
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Workflow finished with failures" in out
        assert "action_a" in out
        assert "Skipped actions: action_b, action_c" in out

    def test_failed_without_skipped_omits_skipped_line(self, tmp_path, capsys):
        """Failed actions only (no skipped) → no 'Skipped' line."""
        with pytest.raises(SystemExit):
            self._execute(
                tmp_path,
                {
                    "is_workflow_complete": False,
                    "is_workflow_done": True,
                    "has_any_failed": True,
                    "get_failed_actions": ["action_a"],
                    "get_skipped_actions": [],
                },
            )
        out = capsys.readouterr().out
        assert "Failed actions: action_a" in out
        assert "Skipped" not in out

    def test_failed_finalizes_tracker_before_exit(self, tmp_path):
        """Tracker finalization runs before SystemExit (finally block)."""
        cmd = RunCommand(_make_args())
        wf_mock = _build_workflow_mock(
            tmp_path,
            {
                "is_workflow_complete": False,
                "is_workflow_done": True,
                "has_any_failed": True,
                "get_failed_actions": ["action_a"],
            },
        )
        tracker_inst = MagicMock()
        tracker_inst.start_workflow_run.return_value = "run-123"

        with (
            patch("agent_actions.cli.run.ProjectPathsFactory.create_project_paths") as mock_paths,
            patch("agent_actions.cli.run.find_config_file", return_value=tmp_path / "cfg.yml"),
            patch("agent_actions.cli.run.PromptValidator"),
            patch("agent_actions.cli.run.ConfigRenderingService.render_and_load_config"),
            patch("agent_actions.cli.run.AgentWorkflow", return_value=wf_mock),
            patch("agent_actions.cli.run.RunTracker", return_value=tracker_inst),
            patch.object(cmd, "_run_workflow_execution"),
            pytest.raises(SystemExit),
        ):
            mock_paths.return_value = MagicMock(
                prompt_dir=tmp_path,
                agent_config_dir=tmp_path,
                template_dir=tmp_path,
                rendered_workflows_dir=tmp_path,
                default_config_path=tmp_path / "default.yml",
                io_dir=tmp_path,
            )
            cmd.execute(project_root=tmp_path)

        tracker_inst.finalize_workflow_run.assert_called_once()
        assert tracker_inst.finalize_workflow_run.call_args[1]["status"] == "FAILED"

    # -- PAUSED paths --------------------------------------------------------

    def test_batch_submitted_names_actions(self, tmp_path, capsys):
        """Actual batch jobs → PAUSED with action names."""
        tracker = self._execute(
            tmp_path,
            {
                "is_workflow_complete": False,
                "is_workflow_done": False,
                "get_batch_submitted_actions": ["action_b"],
            },
        )
        out = capsys.readouterr().out
        assert "batch job(s) submitted for: action_b" in out
        assert "Run again to check status and continue" in out
        assert tracker.finalize_workflow_run.call_args[1]["status"] == "PAUSED"

    def test_not_done_no_batch_shows_generic_paused(self, tmp_path, capsys):
        """Not done, no batch → generic paused with summary."""
        tracker = self._execute(
            tmp_path,
            {
                "is_workflow_complete": False,
                "is_workflow_done": False,
                "get_batch_submitted_actions": [],
                "get_summary": {"pending": 2, "completed": 1},
            },
        )
        out = capsys.readouterr().out
        assert "Workflow paused for:" in out
        assert "pending: 2" in out
        assert "completed: 1" in out
        assert "Run again to continue" in out
        assert "batch" not in out.lower()
        assert tracker.finalize_workflow_run.call_args[1]["status"] == "PAUSED"
