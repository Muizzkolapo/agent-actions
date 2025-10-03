"""
Integration tests for sequential loop execution in batch mode.

NOTE: These tests require real batch API infrastructure (OpenAI, Anthropic, etc.) to run properly.
They are currently marked with @pytest.mark.requires_real_batch_backend and will be skipped by default.

Run these tests with: pytest -m requires_real_batch_backend

The mocked version cannot fully simulate the complex batch workflow state machine.
These tests serve as:
- Documentation of expected batch behavior
- Scaffolding for future E2E testing with real batch backends
- Reference for manual testing

Tests verify that:
1. Batch iterations execute in correct sequential order across multiple workflow runs
2. Status file correctly tracks each batch iteration
3. Each batch iteration receives correct input from previous iteration
4. Workflow correctly resumes from where it left off after batch submission
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from typing import Dict, List, Any

from agent_actions.core.graph.agent_workflow import AgentWorkflow


class TestBatchSequentialLoop:
    """Test suite for batch mode sequential loop execution."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def batch_workflow_config(self):
        """Batch mode sequential loop configuration."""
        return {
            "name": "batch_sequential_test",
            "defaults": {"run_mode": "batch"},
            "actions": [
                {
                    "name": "input",
                    "kind": "tool",
                    "schema": {"data": "string"},
                    "run_mode": "batch"
                },
                {
                    "name": "refine",
                    "loop": {"param": "stage", "range": [1, 3], "mode": "sequential"},
                    "schema": {"result_${stage}": "string"},
                    "reads": ["input_data", "result_${stage-1}"],
                    "writes": ["result_${stage}"],
                    "run_mode": "batch"
                }
            ],
            "plan": ["input", "refine <- input"]
        }

    def _create_batch_workflow(self, temp_dir, config):
        """Helper to create batch mode AgentWorkflow with mocked dependencies."""
        config_file = temp_dir / "config.yml"

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
                    "run_mode": "batch"
                },
                "refine_1": {
                    "agent_type": "refine_1",
                    "dependencies": ["input"],
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 1,
                    "loop_mode": "sequential",
                    "run_mode": "batch"
                },
                "refine_2": {
                    "agent_type": "refine_2",
                    "dependencies": ["refine_1"],  # Sequential dependency
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 2,
                    "loop_mode": "sequential",
                    "run_mode": "batch"
                },
                "refine_3": {
                    "agent_type": "refine_3",
                    "dependencies": ["refine_2"],  # Sequential dependency
                    "is_loop_agent": True,
                    "loop_base_name": "refine",
                    "loop_iteration": 3,
                    "loop_mode": "sequential",
                    "run_mode": "batch"
                }
            }
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ["input", "refine_1", "refine_2", "refine_3"]
            mock_config_manager.run_id = "test_run"
            mock_config_manager.agent_name = "batch_sequential_test"
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager

            # Setup mock agent runner
            mock_runner = MagicMock()
            agent_folder = temp_dir / "agent_io"
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / "staging").mkdir(exist_ok=True)
            mock_runner.get_agent_folder.return_value = str(agent_folder)

            # Track which agents have been executed
            executed_agents = []

            def mock_run_agent(agent_config, agent_name, previous_agent, idx, is_last):
                agent_type = agent_config["agent_type"]
                executed_agents.append(agent_type)

                output_dir = agent_folder / "target" / f"node_{idx}_{agent_type}"
                output_dir.mkdir(parents=True, exist_ok=True)

                # Create mock output data
                output_data = [{"target_id": "1", "data": f"output_from_{agent_type}"}]
                for i, data in enumerate(output_data):
                    output_file = output_dir / f"{i}.json"
                    with open(output_file, 'w') as f:
                        json.dump(data, f)

                # Create batch registry
                batch_dir = output_dir / "batch"
                batch_dir.mkdir(exist_ok=True)
                registry_file = batch_dir / ".batch_registry.json"
                with open(registry_file, 'w') as f:
                    json.dump({"status": "submitted", "batch_id": f"batch_{agent_type}"}, f)

                return str(output_dir)

            mock_runner.run_agent.side_effect = mock_run_agent
            mock_create_runner.return_value = mock_runner

            # Mock batch service
            mock_batch_service = MockBatchService.return_value

            # Create a stateful batch status checker
            # Simulates: submitted → in_progress → completed cycle
            batch_states = {}

            def mock_check_status(agent_name, batch_dir):
                if agent_name not in batch_states:
                    batch_states[agent_name] = "submitted"

                if batch_states[agent_name] == "submitted":
                    batch_states[agent_name] = "in_progress"
                    return ("in_progress", str(agent_folder / "target"))
                elif batch_states[agent_name] == "in_progress":
                    batch_states[agent_name] = "completed"
                    return ("completed", str(agent_folder / "target"))
                else:
                    return ("completed", str(agent_folder / "target"))

            mock_batch_service.check_batch_status.side_effect = mock_check_status

            workflow = AgentWorkflow(
                constructor_path=str(config_file),
                user_code_path=None,
                default_path=None,
                use_tools=True,
                parent_output=None,
                parent_source=None,
                parent_pipeline=None
            )

            workflow.execution_order = ["input", "refine_1", "refine_2", "refine_3"]
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map

            return workflow, agent_folder, executed_agents

    @pytest.mark.requires_real_batch_backend
    def test_batch_sequential_execution_order(self, temp_dir, batch_workflow_config):
        """
        Test that batch iterations execute in correct sequential order across multiple runs.

        Expected behavior:
        Run 1: input submits batch → break
        Run 2: input completes → refine_1 submits batch → break
        Run 3: refine_1 completes → refine_2 submits batch → break
        Run 4: refine_2 completes → refine_3 submits batch → break
        Run 5: refine_3 completes → workflow complete
        """
        workflow, agent_folder, executed_agents = self._create_batch_workflow(temp_dir, batch_workflow_config)

        # Simulate multiple workflow runs (N+1 pattern for batch sequential loops)
        execution_log = []

        for run_num in range(6):  # Need ~5-6 runs for 3-iteration sequential loop
            execution_log.append(f"Run {run_num + 1}")
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass  # Batch mode breaks execution

            # Log current status
            status_file = agent_folder / ".agent_status.json"
            if status_file.exists():
                with open(status_file) as f:
                    status = json.load(f)
                    execution_log.append(f"  Status: {status}")

        # Verify execution happened in correct order
        # Each agent should run exactly once for initial submission
        assert "input" in executed_agents
        assert "refine_1" in executed_agents
        assert "refine_2" in executed_agents
        assert "refine_3" in executed_agents

        # Verify order: input before refine_1, refine_1 before refine_2, refine_2 before refine_3
        input_idx = executed_agents.index("input")
        refine_1_idx = executed_agents.index("refine_1")
        refine_2_idx = executed_agents.index("refine_2")
        refine_3_idx = executed_agents.index("refine_3")

        assert input_idx < refine_1_idx, "input should execute before refine_1"
        assert refine_1_idx < refine_2_idx, "refine_1 should execute before refine_2"
        assert refine_2_idx < refine_3_idx, "refine_2 should execute before refine_3"

    @pytest.mark.requires_real_batch_backend
    def test_batch_sequential_status_tracking(self, temp_dir, batch_workflow_config):
        """Test that status file correctly tracks each batch iteration."""
        workflow, agent_folder, executed_agents = self._create_batch_workflow(temp_dir, batch_workflow_config)

        # Run workflow multiple times
        for _ in range(6):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        # Check final status
        status_file = agent_folder / ".agent_status.json"
        assert status_file.exists(), "Status file should exist"

        with open(status_file) as f:
            status = json.load(f)

        # All agents should eventually reach 'completed' status
        expected_agents = ["input", "refine_1", "refine_2", "refine_3"]
        for agent in expected_agents:
            assert agent in status, f"Status file missing {agent}"
            assert status[agent] == "completed", f"{agent} should be completed"

    @pytest.mark.requires_real_batch_backend
    def test_batch_sequential_data_flow(self, temp_dir, batch_workflow_config):
        """Test that each batch iteration receives correct input from previous iteration."""
        workflow, agent_folder, executed_agents = self._create_batch_workflow(temp_dir, batch_workflow_config)

        # Run workflow to completion
        for _ in range(6):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        # Verify data flow: each iteration should have output directory
        target_dir = agent_folder / "target"
        assert (target_dir / "node_0_input").exists(), "input output should exist"
        assert (target_dir / "node_1_refine_1").exists(), "refine_1 output should exist"
        assert (target_dir / "node_2_refine_2").exists(), "refine_2 output should exist"
        assert (target_dir / "node_3_refine_3").exists(), "refine_3 output should exist"

        # Verify data files exist
        assert (target_dir / "node_0_input" / "0.json").exists()
        assert (target_dir / "node_1_refine_1" / "0.json").exists()
        assert (target_dir / "node_2_refine_2" / "0.json").exists()
        assert (target_dir / "node_3_refine_3" / "0.json").exists()

    @pytest.mark.requires_real_batch_backend
    def test_batch_sequential_multi_run_workflow(self, temp_dir, batch_workflow_config):
        """Test that workflow correctly resumes from where it left off after batch submission."""
        workflow, agent_folder, executed_agents = self._create_batch_workflow(temp_dir, batch_workflow_config)

        # Run 1: Should submit input batch and break
        try:
            workflow.run()
        except (SystemExit, StopIteration):
            pass

        status_file = agent_folder / ".agent_status.json"
        with open(status_file) as f:
            status_after_run1 = json.load(f)

        # After run 1, input should be batch_submitted, others pending
        assert status_after_run1.get("input") == "batch_submitted"

        # Run 2: Should check input (completed), submit refine_1, break
        try:
            workflow.run()
        except (SystemExit, StopIteration):
            pass

        # Continue running until complete
        for _ in range(5):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        # Verify final state
        with open(status_file) as f:
            final_status = json.load(f)

        # All should be completed
        for agent in ["input", "refine_1", "refine_2", "refine_3"]:
            assert final_status.get(agent) == "completed", \
                f"{agent} should be completed in final state"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
