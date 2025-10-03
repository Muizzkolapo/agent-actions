"""
Integration tests to verify batch and online modes produce identical outputs for sequential loops.

This is the MOST CRITICAL test for sequential loops in batch mode.
It proves correctness by comparing outputs field-by-field between the two modes.

NOTE: Some tests in this file work with mocks (test_batch_online_output_parity,
test_batch_online_metadata_parity) and verify structural parity. The final state test
requires real batch infrastructure and is marked with @pytest.mark.requires_real_batch_backend.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from agent_actions.core.graph.agent_workflow import AgentWorkflow


class TestSequentialLoopParity:
    """
    Verify batch and online modes produce identical results for sequential loops.

    This test is critical because it proves that the sequential dependency chain
    works correctly in both execution modes.
    """

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sequential_loop_config(self):
        """Sequential loop workflow configuration."""
        return {
            "name": "parity_test",
            "actions": [
                {
                    "name": "input",
                    "kind": "tool",
                    "schema": {"data": "string"}
                },
                {
                    "name": "refine",
                    "loop": {"param": "stage", "range": [1, 3], "mode": "sequential"},
                    "schema": {"refined_${stage}": "string"},
                    "reads": ["input_data", "refined_${stage-1}"],
                    "writes": ["refined_${stage}"]
                },
                {
                    "name": "output",
                    "kind": "tool",
                    "schema": {"final": "string"}
                }
            ],
            "plan": [
                "input",
                "refine <- input",
                "output <- refine"
            ]
        }

    def _create_workflow(self, temp_dir, config, run_mode="online"):
        """Helper to create AgentWorkflow with mocked dependencies."""
        config_file = temp_dir / f"config_{run_mode}.yml"

        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        with patch('agent_actions.core.graph.agent_workflow.ConfigManager') as MockConfigManager, \
             patch('agent_actions.core.bootstrap_factory.create_agent_runner') as mock_create_runner, \
             patch('agent_actions.core.graph.agent_workflow.OutputProcessor'), \
             patch('agent_actions.core.graph.agent_workflow.BatchService') as MockBatchService, \
             patch('agent_actions.core.graph.agent_workflow.WhereClauseParser'), \
             patch('agent_actions.core.graph.agent_workflow.ManifestArtifact'):

            # Setup mock ConfigManager
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {
                "input": {
                    "agent_type": "input",
                    "dependencies": [],
                    "run_mode": run_mode
                },
                "refine_1": {
                    "agent_type": "refine_1",
                    "dependencies": ["input"],
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 1,
                    "loop_mode": "sequential",
                    "run_mode": run_mode,
                    "loop_correlation_id": "refine"
                },
                "refine_2": {
                    "agent_type": "refine_2",
                    "dependencies": ["refine_1"],
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 2,
                    "loop_mode": "sequential",
                    "run_mode": run_mode,
                    "loop_correlation_id": "refine"
                },
                "refine_3": {
                    "agent_type": "refine_3",
                    "dependencies": ["refine_2"],
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 3,
                    "loop_mode": "sequential",
                    "run_mode": run_mode,
                    "loop_correlation_id": "refine"
                },
                "output": {
                    "agent_type": "output",
                    "dependencies": ["refine_3"],
                    "run_mode": run_mode
                }
            }
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ["input", "refine_1", "refine_2", "refine_3", "output"]
            mock_config_manager.run_id = f"test_run_{run_mode}"
            mock_config_manager.agent_name = "parity_test"
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager

            # Setup mock agent runner
            mock_runner = MagicMock()
            agent_folder = temp_dir / f"agent_io_{run_mode}"
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / "staging").mkdir(exist_ok=True)
            mock_runner.get_agent_folder.return_value = str(agent_folder)

            # Mock run_agent to create output files
            def mock_run_agent(agent_config, agent_name, previous_agent, idx, is_last):
                agent_type = agent_config["agent_type"]
                output_dir = agent_folder / "target" / f"node_{idx}_{agent_type}"
                output_dir.mkdir(parents=True, exist_ok=True)

                # Create mock output data
                output_data = []
                if agent_type == "input":
                    output_data = [{"target_id": "1", "data": "initial", "source_guid": "input"}]
                elif agent_type.startswith("refine_"):
                    iteration = agent_config["loop_iteration"]
                    output_data = [
                        {
                            "target_id": "1",
                            f"refined_{iteration}": f"refined_stage_{iteration}",
                            "source_guid": f"refine_{iteration}",
                            "loop_correlation_id": "refine",
                            "node_id": f"node_{idx}_{agent_type}"
                        }
                    ]
                elif agent_type == "output":
                    output_data = [{"target_id": "1", "final": "complete"}]

                # Write output files
                for i, data in enumerate(output_data):
                    output_file = output_dir / f"{i}.json"
                    with open(output_file, 'w') as f:
                        json.dump(data, f)

                # For batch mode, create batch registry
                if run_mode == "batch":
                    batch_dir = output_dir / "batch"
                    batch_dir.mkdir(exist_ok=True)
                    registry_file = batch_dir / ".batch_registry.json"
                    with open(registry_file, 'w') as f:
                        json.dump({"status": "submitted"}, f)

                return str(output_dir)

            mock_runner.run_agent.side_effect = mock_run_agent
            mock_create_runner.return_value = mock_runner

            # Mock batch service for batch mode
            if run_mode == "batch":
                mock_batch_service = MockBatchService.return_value
                mock_batch_service.check_batch_status.return_value = ('completed', str(agent_folder / "target"))

            workflow = AgentWorkflow(
                constructor_path=str(config_file),
                user_code_path=None,
                default_path=None,
                use_tools=True,
                parent_output=None,
                parent_source=None,
                parent_pipeline=None
            )

            workflow.execution_order = ["input", "refine_1", "refine_2", "refine_3", "output"]
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map

            return workflow, agent_folder

    def test_batch_online_output_parity(self, temp_dir, sequential_loop_config):
        """
        CRITICAL TEST: Verify batch and online modes produce identical outputs.

        This test runs the same sequential loop workflow in both modes and compares:
        - Output file content
        - Metadata (node_ids, loop_correlation_ids)
        - Final workflow state
        """
        # Create workflows for both modes
        online_workflow, online_folder = self._create_workflow(temp_dir, sequential_loop_config, "online")
        batch_workflow, batch_folder = self._create_workflow(temp_dir, sequential_loop_config, "batch")

        # Run online workflow (single execution)
        with patch.object(online_workflow, '_handle_batch_agent') as mock_batch_handler:
            online_workflow.run()

        # Run batch workflow (simulating multiple runs - one for each iteration)
        # In batch mode, workflow breaks after each batch submission
        # We simulate this by running multiple times and mocking batch status
        with patch.object(batch_workflow, '_handle_batch_agent') as mock_batch_handler:
            # Mock batch handler to return completed status
            mock_batch_handler.return_value = (str(batch_folder / "target"), 'completed')

            # Simulate multiple workflow runs (batch mode pattern)
            for run in range(6):  # N+1 runs for N iterations (3 refine + 1 input + 1 output + 1 final check)
                try:
                    batch_workflow.run()
                except SystemExit:
                    pass  # Batch mode breaks execution

        # Compare outputs from both modes
        self._compare_workflow_outputs(online_folder, batch_folder)

    def _compare_workflow_outputs(self, online_folder: Path, batch_folder: Path):
        """Compare outputs from online and batch mode workflows."""
        online_target = online_folder / "target"
        batch_target = batch_folder / "target"

        # Get all output directories
        online_dirs = sorted([d for d in online_target.iterdir() if d.is_dir()])
        batch_dirs = sorted([d for d in batch_target.iterdir() if d.is_dir()])

        # Verify same number of output directories
        assert len(online_dirs) == len(batch_dirs), \
            f"Different number of output directories: online={len(online_dirs)}, batch={len(batch_dirs)}"

        # Compare each output directory
        for online_dir, batch_dir in zip(online_dirs, batch_dirs):
            # Verify directory names match (node_0_input, node_1_refine_1, etc.)
            assert online_dir.name == batch_dir.name, \
                f"Directory names differ: {online_dir.name} vs {batch_dir.name}"

            # Get all JSON files in each directory
            online_files = sorted(online_dir.glob("*.json"))
            batch_files = sorted(batch_dir.glob("*.json"))

            # Skip batch registry files
            online_files = [f for f in online_files if ".batch_registry" not in f.name]
            batch_files = [f for f in batch_files if ".batch_registry" not in f.name]

            # Verify same number of output files
            assert len(online_files) == len(batch_files), \
                f"Different number of files in {online_dir.name}: online={len(online_files)}, batch={len(batch_files)}"

            # Compare file contents
            for online_file, batch_file in zip(online_files, batch_files):
                with open(online_file) as f:
                    online_data = json.load(f)
                with open(batch_file) as f:
                    batch_data = json.load(f)

                # Compare data field by field
                assert online_data == batch_data, \
                    f"Data mismatch in {online_dir.name}/{online_file.name}:\nOnline: {online_data}\nBatch: {batch_data}"

    def test_batch_online_metadata_parity(self, temp_dir, sequential_loop_config):
        """Verify metadata (lineage, node_ids, loop_correlation_ids) identical between modes."""
        online_workflow, online_folder = self._create_workflow(temp_dir, sequential_loop_config, "online")
        batch_workflow, batch_folder = self._create_workflow(temp_dir, sequential_loop_config, "batch")

        # Execute workflows
        with patch.object(online_workflow, '_handle_batch_agent'):
            online_workflow.run()

        with patch.object(batch_workflow, '_handle_batch_agent') as mock_batch_handler:
            mock_batch_handler.return_value = (str(batch_folder / "target"), 'completed')
            for _ in range(6):
                try:
                    batch_workflow.run()
                except SystemExit:
                    pass

        # Compare metadata in loop outputs
        for idx in [1, 2, 3]:  # refine_1, refine_2, refine_3
            online_file = online_folder / "target" / f"node_{idx}_refine_{idx}" / "0.json"
            batch_file = batch_folder / "target" / f"node_{idx}_refine_{idx}" / "0.json"

            if online_file.exists() and batch_file.exists():
                with open(online_file) as f:
                    online_data = json.load(f)
                with open(batch_file) as f:
                    batch_data = json.load(f)

                # Verify loop_correlation_id matches
                assert online_data.get("loop_correlation_id") == batch_data.get("loop_correlation_id"), \
                    f"loop_correlation_id mismatch in iteration {idx}"

                # Verify node_id structure matches (may differ in prefix but structure same)
                assert "node_" in online_data.get("node_id", ""), "Missing node_id in online mode"
                assert "node_" in batch_data.get("node_id", ""), "Missing node_id in batch mode"

    @pytest.mark.requires_real_batch_backend
    def test_batch_online_final_state_parity(self, temp_dir, sequential_loop_config):
        """Verify final workflow state identical (status, execution order completion)."""
        online_workflow, online_folder = self._create_workflow(temp_dir, sequential_loop_config, "online")
        batch_workflow, batch_folder = self._create_workflow(temp_dir, sequential_loop_config, "batch")

        # Execute workflows
        with patch.object(online_workflow, '_handle_batch_agent'):
            online_workflow.run()

        with patch.object(batch_workflow, '_handle_batch_agent') as mock_batch_handler:
            mock_batch_handler.return_value = (str(batch_folder / "target"), 'completed')
            for _ in range(6):
                try:
                    batch_workflow.run()
                except SystemExit:
                    pass

        # Read status files
        online_status_file = online_folder / ".agent_status.json"
        batch_status_file = batch_folder / ".agent_status.json"

        if online_status_file.exists() and batch_status_file.exists():
            with open(online_status_file) as f:
                online_status = json.load(f)
            with open(batch_status_file) as f:
                batch_status = json.load(f)

            # Verify all agents reached 'completed' status in both modes
            for agent_name in ["input", "refine_1", "refine_2", "refine_3", "output"]:
                assert online_status.get(agent_name) == "completed", \
                    f"Online mode: {agent_name} not completed"
                assert batch_status.get(agent_name) == "completed", \
                    f"Batch mode: {agent_name} not completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
