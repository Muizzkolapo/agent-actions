"""Tests for AgentManager.agent_exists() -- regression coverage for P1-5.

The bug: agent_exists() was a @staticmethod that referenced `self`, causing
NameError at runtime. The fix replaces `self.get_agent_paths(...)` with
`AgentManager.get_agent_paths(...)`.
"""

from unittest.mock import patch

from agent_actions.errors import AgentNotFoundError
from agent_actions.llm.realtime.handlers import AgentManager


class TestAgentExists:
    """Regression tests for AgentManager.agent_exists()."""

    @patch.object(AgentManager, "get_agent_paths")
    def test_returns_true_when_agent_config_dir_exists(self, mock_get_paths, tmp_path):
        """agent_exists returns True when the config directory exists on disk."""
        config_dir = tmp_path / "agent_config"
        config_dir.mkdir()
        mock_get_paths.return_value = (
            str(config_dir),
            str(tmp_path / "io"),
            str(tmp_path / "logs"),
        )

        assert AgentManager.agent_exists("my_agent") is True
        mock_get_paths.assert_called_once_with("my_agent", project_root=None)

    @patch.object(AgentManager, "get_agent_paths")
    def test_returns_false_when_get_agent_paths_raises(self, mock_get_paths):
        """agent_exists returns False when get_agent_paths raises AgentNotFoundError."""
        mock_get_paths.side_effect = AgentNotFoundError(
            "not found", context={"agent_name": "missing"}
        )

        assert AgentManager.agent_exists("missing") is False

    @patch.object(AgentManager, "get_agent_paths")
    def test_returns_false_when_config_dir_does_not_exist(self, mock_get_paths, tmp_path):
        """agent_exists returns False when config dir path doesn't exist on disk."""
        nonexistent = tmp_path / "does_not_exist"
        mock_get_paths.return_value = (
            str(nonexistent),
            str(tmp_path / "io"),
            str(tmp_path / "logs"),
        )

        assert AgentManager.agent_exists("ghost_agent") is False
