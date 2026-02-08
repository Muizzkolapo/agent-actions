"""
Tests for AgentWorkflow passthrough marker cleanup functionality.
Tests that .passthrough_processed marker files are properly cleaned up to avoid
interfering with subsequent file processing.
"""

import pytest
from unittest.mock import Mock
from pathlib import Path
import tempfile
import json
from rich.console import Console
from agent_actions.workflow.coordinator import AgentWorkflow


class TestAgentWorkflowPassthroughCleanup:
    """Test suite for AgentWorkflow passthrough marker cleanup."""

    @pytest.fixture
    def mock_console(self):
        """Create a mock console for testing."""
        return Mock(spec=Console)

    @pytest.fixture
    def workflow(self, mock_console):
        """Create an AgentWorkflow instance for testing."""
        workflow = Mock(spec=AgentWorkflow)
        workflow.ephemeral_directories = []
        workflow.previous_agent_type = None
        workflow._update_status = Mock()
        workflow.console = mock_console
        workflow.agent_configs = [{"name": "test_agent", "ephemeral": False}]
        return workflow

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            agent_io = workspace / "agent_io"
            target = agent_io / "target"
            node_output = target / "node_2_classify_feynman"
            node_output.mkdir(parents=True)
            yield {
                "workspace": workspace,
                "agent_io": agent_io,
                "target": target,
                "node_output": node_output,
            }

    def test_passthrough_marker_cleanup_success(self, workflow, temp_workspace):
        """Test that passthrough marker file is successfully cleaned up after detection."""
        node_output_dir = temp_workspace["node_output"]
        passthrough_marker = node_output_dir / ".passthrough_processed"
        passthrough_marker.touch()
        assert passthrough_marker.exists()
        workflow.ephemeral_directories = []
        workflow.previous_agent_type = None
        agent_config = {"name": "test_agent", "ephemeral": False}
        agent_name = "test_agent"
        idx = 0
        total_agents = 1
        if passthrough_marker.exists():
            workflow._update_status(agent_name, "completed")
            workflow.previous_agent_type = agent_name
            workflow.ephemeral_directories.append(
                {
                    "output_folder": str(node_output_dir),
                    "ephemeral": agent_config.get("ephemeral", False),
                }
            )
            try:
                passthrough_marker.unlink()
            except FileNotFoundError:
                pass
        assert not passthrough_marker.exists()
        workflow._update_status.assert_called_once_with(agent_name, "completed")
        assert workflow.previous_agent_type == agent_name
        assert len(workflow.ephemeral_directories) == 1
        assert workflow.ephemeral_directories[0]["output_folder"] == str(node_output_dir)

    def test_passthrough_marker_cleanup_already_removed(self, workflow, temp_workspace):
        """Test cleanup handles gracefully when marker file is already removed."""
        node_output_dir = temp_workspace["node_output"]
        passthrough_marker = node_output_dir / ".passthrough_processed"
        assert not passthrough_marker.exists()
        try:
            passthrough_marker.unlink()
        except FileNotFoundError:
            pass
        assert not passthrough_marker.exists()

    def test_passthrough_marker_prevents_file_processing_issues(self, workflow, temp_workspace):
        """Test that marker cleanup prevents issues with file processing workflows."""
        node_output_dir = temp_workspace["node_output"]
        passthrough_marker = node_output_dir / ".passthrough_processed"
        passthrough_marker.touch()
        data_file = node_output_dir / "data.json"
        with open(data_file, "w") as f:
            json.dump([{"test": "data"}], f)
        all_files = list(node_output_dir.glob("*"))
        assert passthrough_marker in all_files
        assert data_file in all_files
        if passthrough_marker.exists():
            passthrough_marker.unlink()
        remaining_files = list(node_output_dir.glob("*"))
        assert passthrough_marker not in remaining_files
        assert data_file in remaining_files
        json_files = list(node_output_dir.glob("*.json"))
        assert len(json_files) == 1
        assert data_file in json_files

    def test_multiple_passthrough_markers_cleanup(self, workflow, temp_workspace):
        """Test cleanup handles multiple passthrough scenarios correctly."""
        base_dir = temp_workspace["target"]
        node_dirs = []
        markers = []
        for i in range(3):
            node_dir = base_dir / f"node_{i}_agent"
            node_dir.mkdir()
            marker = node_dir / ".passthrough_processed"
            marker.touch()
            node_dirs.append(node_dir)
            markers.append(marker)
        for marker in markers:
            assert marker.exists()
        for marker in markers:
            if marker.exists():
                try:
                    marker.unlink()
                except FileNotFoundError:
                    pass
        for marker in markers:
            assert not marker.exists()
        for node_dir in node_dirs:
            assert node_dir.exists()

    def test_passthrough_data_integrity_after_cleanup(self, workflow, temp_workspace):
        """Test that actual passthrough data files are not affected by marker cleanup."""
        node_output_dir = temp_workspace["node_output"]
        passthrough_marker = node_output_dir / ".passthrough_processed"
        passthrough_marker.touch()
        data_file = node_output_dir / "passthrough_data.json"
        test_data = [
            {
                "source_guid": "test-guid-1",
                "content": {"test": "passthrough content"},
                "metadata": {"skipped_by_where_clause": True},
            }
        ]
        with open(data_file, "w") as f:
            json.dump(test_data, f)
        assert passthrough_marker.exists()
        assert data_file.exists()
        if passthrough_marker.exists():
            passthrough_marker.unlink()
        assert not passthrough_marker.exists()
        assert data_file.exists()
        with open(data_file, "r") as f:
            loaded_data = json.load(f)
            assert loaded_data == test_data
