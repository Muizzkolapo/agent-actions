"""Tests for derive_workflow_root() — safe workflow root discovery."""

from pathlib import Path
from unittest.mock import patch

from agent_actions.utils.path_utils import derive_workflow_root


class TestAgentIoFastPath:
    """When 'agent_io' appears in path parts, truncate there."""

    def test_typical_input_path(self, tmp_path):
        workflow = tmp_path / "my_workflow"
        io_dir = workflow / "agent_io" / "input"
        io_dir.mkdir(parents=True)
        assert derive_workflow_root(str(io_dir)) == workflow

    def test_agent_io_deep_in_path(self, tmp_path):
        workflow = tmp_path / "project" / "workflows" / "wf1"
        io_dir = workflow / "agent_io" / "source" / "sub"
        io_dir.mkdir(parents=True)
        assert derive_workflow_root(str(io_dir)) == workflow


class TestWalkUpFallback:
    """When no 'agent_io' in path, walk up looking for agent_config/ sibling."""

    def test_finds_agent_config_sibling(self, tmp_path):
        workflow = tmp_path / "my_workflow"
        (workflow / "agent_config").mkdir(parents=True)
        nested = workflow / "some" / "deep" / "dir"
        nested.mkdir(parents=True)
        assert derive_workflow_root(str(nested)) == workflow

    def test_finds_agent_config_at_immediate_parent(self, tmp_path):
        workflow = tmp_path / "my_workflow"
        (workflow / "agent_config").mkdir(parents=True)
        child = workflow / "seed_data"
        child.mkdir(parents=True)
        assert derive_workflow_root(str(child)) == workflow


class TestShallowAndEdgePaths:
    """Shallow paths (e.g. /tmp, /) must not escape to unexpected locations."""

    def test_shallow_path_without_markers_returns_self(self, tmp_path):
        # tmp_path itself has no agent_io or agent_config — should return tmp_path
        result = derive_workflow_root(str(tmp_path))
        assert result == tmp_path

    def test_root_path_returns_root(self):
        result = derive_workflow_root("/")
        # Should not crash; returns / (which is a directory)
        assert result == Path("/")

    def test_nonexistent_path_returns_parent(self, tmp_path):
        missing = tmp_path / "nonexistent_file.txt"
        # missing is not a dir, so fallback returns its parent
        result = derive_workflow_root(str(missing))
        assert result == tmp_path

    def test_relative_path_starting_with_agent_io(self):
        # idx == 0 edge case: relative path "agent_io/input" has no prefix to truncate
        # Should fall through to walk-up / fallback, not crash
        result = derive_workflow_root("agent_io/input")
        assert isinstance(result, Path)

    def test_fallback_emits_warning(self, tmp_path):
        # No agent_io or agent_config — should log a warning
        with patch("agent_actions.utils.path_utils.logger") as mock_logger:
            derive_workflow_root(str(tmp_path))
        mock_logger.warning.assert_called_once()
        assert "Could not determine workflow root" in mock_logger.warning.call_args[0][0]
