"""Tests for RunCommand.execute() project_root wiring."""

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
        "upstream": False,
        "downstream": False,
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
