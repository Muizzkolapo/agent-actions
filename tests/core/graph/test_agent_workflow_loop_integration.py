"""Tests for AgentWorkflow integration with LoopOutputCorrelator."""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, call
from typing import Dict, List, Any

from agent_actions.core.graph.agent_workflow import AgentWorkflow
from agent_actions.core.graph.loop_correlator import LoopOutputCorrelator


class TestAgentWorkflowLoopIntegration:
    """Test suite for AgentWorkflow's loop correlation integration."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_components(self, temp_dir):
        """Create mock components for AgentWorkflow."""
        mock_runner = MagicMock()
        mock_runner.get_agent_folder.return_value = str(temp_dir / "agent_io")

        mock_manifest = MagicMock()
        mock_batch_service = MagicMock()
        mock_parser = MagicMock()

        return {
            'runner': mock_runner,
            'manifest': mock_manifest,
            'batch_service': mock_batch_service,
            'parser': mock_parser,
            'temp_dir': temp_dir
        }

    @pytest.fixture
    def workflow_with_loops(self, mock_components):
        """Create an AgentWorkflow with loop configuration."""
        temp_dir = mock_components['temp_dir']

        # Create a mock config file
        config_file = temp_dir / "config.yml"
        config_data = {
            "name": "test_workflow",
            "execution_plan": ["extract", "process", "aggregate", "validate"],
            "actions": [
                {"name": "extract", "tool": "mock_tool"},
                {"name": "process", "tool": "mock_tool", "loop": {"param": "idx", "range": [1, 3]}},
                {"name": "aggregate", "tool": "mock_tool"},
                {"name": "validate", "tool": "mock_tool"}
            ]
        }

        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with patch('agent_actions.core.graph.agent_workflow.ConfigManager') as MockConfigManager, \
             patch('agent_actions.core.bootstrap_factory.create_agent_runner') as mock_create_runner, \
             patch('agent_actions.core.graph.agent_workflow.OutputProcessor'), \
             patch('agent_actions.core.graph.agent_workflow.BatchService'), \
             patch('agent_actions.core.graph.agent_workflow.WhereClauseParser'), \
             patch('agent_actions.core.graph.agent_workflow.ManifestArtifact'):

            # Setup mock ConfigManager
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {
                "extract": {"agent_type": "extract", "dependencies": []},
                "process_1": {"agent_type": "process", "dependencies": ["extract"]},
                "process_2": {"agent_type": "process", "dependencies": ["extract"]},
                "process_3": {"agent_type": "process", "dependencies": ["extract"]},
                "aggregate": {"agent_type": "aggregate", "dependencies": ["process"]},
                "validate": {"agent_type": "validate", "dependencies": ["aggregate"]}
            }
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ["extract", "process_1", "process_2", "process_3", "aggregate", "validate"]
            mock_config_manager.run_id = "test_run"
            mock_config_manager.agent_name = "test_workflow"
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager

            # Setup mock agent runner
            mock_runner = mock_components['runner']
            mock_create_runner.return_value = mock_runner

            workflow = AgentWorkflow(
                constructor_path=str(config_file),
                user_code_path=None,
                default_path=None,
                use_tools=True,
                parent_output=None,
                parent_source=None,
                parent_pipeline=None
            )

            workflow.execution_order = ["extract", "process_1", "process_2", "process_3", "aggregate", "validate"]
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map

            # Create required directories
            agent_folder = Path(mock_components['runner'].get_agent_folder())
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / "staging").mkdir(exist_ok=True)

            return workflow

    def test_loop_correlator_initialization(self, workflow_with_loops):
        """Test that LoopOutputCorrelator is initialized correctly."""
        assert hasattr(workflow_with_loops, 'loop_correlator')
        assert isinstance(workflow_with_loops.loop_correlator, LoopOutputCorrelator)

    def test_get_input_directory_with_loop_correlation(self, workflow_with_loops, mock_components):
        """Test _get_input_directory when loop correlation is needed."""
        # Create loop output directories with test data
        agent_folder = Path(mock_components['runner'].get_agent_folder())

        for i in range(1, 4):
            loop_dir = agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

            test_data = [{
                "source_guid": "test-1",
                "content": {f"field_{i}": f"value_{i}"}
            }]

            with open(loop_dir / "data.json", 'w') as f:
                json.dump(test_data, f)

        # Test getting input directory for aggregate agent (should trigger correlation)
        with patch.object(workflow_with_loops, 'console') as mock_console:
            input_dir = workflow_with_loops._get_input_directory(4)  # Index 4 is aggregate

            # Should use correlated directory
            assert "node_4_aggregate" in input_dir

            # Should print correlation message
            mock_console.print.assert_called()
            assert any("Using correlated input" in str(call) for call in mock_console.print.call_args_list)

    def test_get_input_directory_without_correlation(self, workflow_with_loops):
        """Test _get_input_directory for non-loop-dependent agents."""
        # Create previous agent output directory
        agent_folder = Path(workflow_with_loops.agent_runner.get_agent_folder())
        prev_dir = agent_folder / "target" / "node_0_extract"
        prev_dir.mkdir(parents=True, exist_ok=True)

        # Test getting input directory for process_1 (no correlation needed)
        input_dir = workflow_with_loops._get_input_directory(1)

        # Should use standard previous agent directory
        assert "node_0_extract" in input_dir

    def test_get_input_directory_first_agent(self, workflow_with_loops):
        """Test _get_input_directory for the first agent (uses staging)."""
        input_dir = workflow_with_loops._get_input_directory(0)
        assert input_dir.endswith("staging")

    def test_setup_correlation_if_needed_with_loops(self, workflow_with_loops, mock_components):
        """Test _setup_correlation_if_needed when agent depends on loops."""
        # Create loop output directories
        agent_folder = Path(mock_components['runner'].get_agent_folder())

        for i in range(1, 4):
            loop_dir = agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

            with open(loop_dir / "test.json", 'w') as f:
                json.dump([{"source_guid": f"guid-{i}", "content": {"data": i}}], f)

        # Mock the setup_directories method
        original_setup = MagicMock(return_value=("input", "output"))
        workflow_with_loops.agent_runner.setup_directories = original_setup

        with patch.object(workflow_with_loops, 'console'):
            # Setup correlation for aggregate agent
            workflow_with_loops._setup_correlation_if_needed(4)

            # Should have replaced setup_directories
            assert workflow_with_loops.agent_runner.setup_directories != original_setup
            assert hasattr(workflow_with_loops, '_original_setup_directories')

    def test_setup_correlation_if_needed_without_loops(self, workflow_with_loops):
        """Test _setup_correlation_if_needed for non-loop-dependent agents."""
        # Mock the setup_directories method
        original_setup = MagicMock()
        workflow_with_loops.agent_runner.setup_directories = original_setup

        # Setup correlation for extract agent (no loops)
        workflow_with_loops._setup_correlation_if_needed(0)

        # Should not have changed setup_directories
        assert workflow_with_loops.agent_runner.setup_directories == original_setup

    def test_setup_correlation_restore_original(self, workflow_with_loops):
        """Test that original setup_directories is restored after correlation."""
        original_setup = MagicMock()
        workflow_with_loops.agent_runner.setup_directories = original_setup
        workflow_with_loops._original_setup_directories = original_setup

        # Call for non-loop agent after having set up correlation
        workflow_with_loops._setup_correlation_if_needed(5)  # validate agent

        # Should restore original
        assert workflow_with_loops.agent_runner.setup_directories == original_setup

    def test_correlation_fallback_on_failure(self, workflow_with_loops, mock_components):
        """Test fallback to standard input when correlation fails."""
        # Don't create any loop output directories (correlation will fail)

        with patch.object(workflow_with_loops, 'console') as mock_console:
            input_dir = workflow_with_loops._get_input_directory(4)  # aggregate agent

            # Should fall back to standard directory
            assert "node_3_process_3" in input_dir

            # Should print warning message
            mock_console.print.assert_called()
            assert any("Failed to correlate" in str(call) for call in mock_console.print.call_args_list)

    def test_correlation_with_partial_loop_outputs(self, workflow_with_loops, mock_components):
        """Test correlation when some loop outputs are missing."""
        agent_folder = Path(mock_components['runner'].get_agent_folder())

        # Only create outputs for process_1 and process_2 (not process_3)
        for i in range(1, 3):
            loop_dir = agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

            test_data = [{
                "source_guid": "test-1",
                "content": {f"field_{i}": f"value_{i}"}
            }]

            with open(loop_dir / "data.json", 'w') as f:
                json.dump(test_data, f)

        with patch.object(workflow_with_loops, 'console'):
            input_dir = workflow_with_loops._get_input_directory(4)  # aggregate

            # Should still create correlation directory
            assert "node_4_aggregate" in input_dir

            # Verify the correlated data includes partial records
            correlated_file = Path(input_dir) / "data.json"
            if correlated_file.exists():
                with open(correlated_file, 'r') as f:
                    data = json.load(f)
                    assert len(data) > 0
                    assert "field_1" in data[0]["content"]
                    assert "field_2" in data[0]["content"]

    def test_correlation_preserves_filenames(self, workflow_with_loops, mock_components):
        """Test that correlation preserves original filenames."""
        agent_folder = Path(mock_components['runner'].get_agent_folder())
        test_filename = "important_data.json"

        for i in range(1, 4):
            loop_dir = agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

            test_data = [{
                "source_guid": "test-1",
                "content": {f"field_{i}": f"value_{i}"}
            }]

            with open(loop_dir / test_filename, 'w') as f:
                json.dump(test_data, f)

        with patch.object(workflow_with_loops, 'console'):
            input_dir = workflow_with_loops._get_input_directory(4)  # aggregate

            # Verify the original filename is preserved
            correlated_file = Path(input_dir) / test_filename
            assert correlated_file.exists(), f"Expected {test_filename} to be preserved"

    def test_multiple_file_correlation_in_workflow(self, workflow_with_loops, mock_components):
        """Test correlation with multiple files from loop agents."""
        agent_folder = Path(mock_components['runner'].get_agent_folder())
        files = ["file1.json", "file2.json", "file3.json"]

        for i in range(1, 4):
            loop_dir = agent_folder / "target" / f"node_{i}_process_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

            for filename in files:
                test_data = [{
                    "source_guid": f"{filename}-guid",
                    "content": {f"field_{i}": f"{filename}-value_{i}"}
                }]

                with open(loop_dir / filename, 'w') as f:
                    json.dump(test_data, f)

        with patch.object(workflow_with_loops, 'console'):
            input_dir = workflow_with_loops._get_input_directory(4)  # aggregate

            # Verify all files are correlated
            for filename in files:
                correlated_file = Path(input_dir) / filename
                assert correlated_file.exists(), f"Expected {filename} to be correlated"

                with open(correlated_file, 'r') as f:
                    data = json.load(f)
                    assert len(data) == 1
                    # Should have fields from all 3 loops
                    assert all(f"field_{i}" in data[0]["content"] for i in range(1, 4))


class TestAgentWorkflowCorrelationEdgeCases:
    """Test edge cases and error handling in correlation."""

    @pytest.fixture
    def workflow(self, tmp_path):
        """Create a basic workflow for testing edge cases."""
        # Create a mock config file
        config_file = tmp_path / "config.yml"
        config_data = {
            "name": "test",
            "execution_plan": ["a", "b"],
            "actions": [
                {"name": "a", "tool": "mock_tool", "loop": {"param": "idx", "range": [1, 2]}},
                {"name": "b", "tool": "mock_tool"}
            ]
        }

        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        mock_runner = MagicMock()
        mock_runner.get_agent_folder.return_value = str(tmp_path / "agent_io")

        with patch('agent_actions.core.graph.agent_workflow.ConfigManager') as MockConfigManager, \
             patch('agent_actions.core.bootstrap_factory.create_agent_runner', return_value=mock_runner), \
             patch('agent_actions.core.graph.agent_workflow.OutputProcessor'), \
             patch('agent_actions.core.graph.agent_workflow.BatchService'), \
             patch('agent_actions.core.graph.agent_workflow.WhereClauseParser'), \
             patch('agent_actions.core.graph.agent_workflow.ManifestArtifact'):

            # Setup mock ConfigManager
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {
                "a_1": {"agent_type": "a", "dependencies": []},
                "a_2": {"agent_type": "a", "dependencies": []},
                "b": {"agent_type": "b", "dependencies": ["a"]}
            }
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ["a_1", "a_2", "b"]
            mock_config_manager.run_id = "test_run"
            mock_config_manager.agent_name = "test"
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager

            workflow = AgentWorkflow(
                constructor_path=str(config_file),
                user_code_path=None,
                default_path=None,
                use_tools=True,
                parent_output=None,
                parent_source=None,
                parent_pipeline=None
            )

            workflow.execution_order = ["a_1", "a_2", "b"]
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map

            # Create required directories
            agent_folder = Path(mock_runner.get_agent_folder())
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / "staging").mkdir(exist_ok=True)

            return workflow

    def test_empty_loop_outputs(self, workflow):
        """Test handling when loop directories exist but are empty."""
        agent_folder = Path(workflow.agent_runner.get_agent_folder())

        # Create empty loop directories
        for i in range(1, 3):
            loop_dir = agent_folder / "target" / f"node_{i-1}_a_{i}"
            loop_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(workflow, 'console'):
            input_dir = workflow._get_input_directory(2)  # b agent

            # When correlation fails with empty outputs, it still creates correlation directory
            # but it will be empty
            assert "node_2_b" in input_dir or "node_1_a_2" in input_dir

    def test_malformed_json_in_loops(self, workflow):
        """Test handling of malformed JSON in loop outputs."""
        agent_folder = Path(workflow.agent_runner.get_agent_folder())

        # Create loop directory with invalid JSON
        loop_dir = agent_folder / "target" / "node_0_a_1"
        loop_dir.mkdir(parents=True, exist_ok=True)

        with open(loop_dir / "data.json", 'w') as f:
            f.write("not valid json {")

        with patch.object(workflow, 'console'):
            input_dir = workflow._get_input_directory(2)  # b agent

            # Should handle gracefully and fall back
            assert input_dir is not None

    def test_loop_detection_with_similar_names(self, workflow):
        """Test that loop detection correctly identifies loop agents."""
        # Test with names that might be confused
        workflow.execution_order = ["extract", "process_data", "loop_1", "loop_2", "consumer"]
        workflow.agent_configs = {
            "extract": {"dependencies": []},
            "process_data": {"dependencies": ["extract"]},
            "loop_1": {"dependencies": ["process_data"]},
            "loop_2": {"dependencies": ["process_data"]},
            "consumer": {"dependencies": ["loop"]},
        }

        loop_deps = workflow.loop_correlator.detect_loop_dependencies(
            workflow.execution_order, workflow.agent_configs
        )

        # consumer should depend on loop_1 and loop_2
        assert "consumer" in loop_deps
        assert set(loop_deps["consumer"]) == {"loop_1", "loop_2"}

        # process_data should not be detected as depending on loops
        assert "process_data" not in loop_deps


if __name__ == "__main__":
    pytest.main([__file__, "-v"])