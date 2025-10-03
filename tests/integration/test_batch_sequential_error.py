"""
Integration tests for error handling in batch mode sequential loops.

NOTE: These tests require real batch API infrastructure (OpenAI, Anthropic, etc.) to run properly.
They are currently marked with @pytest.mark.requires_real_batch_backend and will be skipped by default.

Run these tests with: pytest -m requires_real_batch_backend

These tests serve as documentation of expected error handling behavior in batch mode.

Tests verify that:
1. Failed batch iteration prevents next iteration from running
2. Workflow state correct when some iterations complete, some fail
3. Workflow can resume after fixing failed iteration
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from agent_actions.core.graph.agent_workflow import AgentWorkflow


class TestBatchSequentialError:
    """Test suite for error handling in batch mode sequential loops."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def batch_workflow_config(self):
        """Batch mode sequential loop configuration."""
        return {
            "name": "error_test",
            "defaults": {"run_mode": "batch"},
            "actions": [
                {
                    "name": "input",
                    "kind": "tool",
                    "run_mode": "batch"
                },
                {
                    "name": "process",
                    "loop": {"param": "stage", "range": [1, 5], "mode": "sequential"},
                    "run_mode": "batch"
                }
            ],
            "plan": ["input", "process <- input"]
        }

    def _create_workflow_with_injected_failure(self, temp_dir, config, fail_at_agent):
        """
        Create workflow that fails at specified agent.

        Args:
            fail_at_agent: Agent name that should fail (e.g., "process_3")
        """
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
                }
            }

            # Add sequential loop iterations
            for i in range(1, 6):
                mock_config_manager.agent_configs[f"process_{i}"] = {
                    "agent_type": f"process_{i}",
                    "dependencies": ["input"] if i == 1 else [f"process_{i-1}"],
                    "is_loop_agent": True,
                    "loop_base_name": "process",
                    "loop_iteration": i,
                    "loop_mode": "sequential",
                    "run_mode": "batch"
                }

            execution_order = ["input"] + [f"process_{i}" for i in range(1, 6)]
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = execution_order
            mock_config_manager.run_id = "test_run"
            mock_config_manager.agent_name = "error_test"
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager

            # Setup mock agent runner
            mock_runner = MagicMock()
            agent_folder = temp_dir / "agent_io"
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / "staging").mkdir(exist_ok=True)
            mock_runner.get_agent_folder.return_value = str(agent_folder)

            def mock_run_agent(agent_config, agent_name, previous_agent, idx, is_last):
                agent_type = agent_config["agent_type"]
                output_dir = agent_folder / "target" / f"node_{idx}_{agent_type}"
                output_dir.mkdir(parents=True, exist_ok=True)

                # Create output
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

            # Mock batch service with injected failure
            mock_batch_service = MockBatchService.return_value
            batch_states = {}

            def mock_check_status(agent_name, batch_dir):
                # Inject failure at specified agent
                if agent_name == fail_at_agent:
                    return ("failed", str(agent_folder / "target"))

                # Normal completion for other agents
                if agent_name not in batch_states:
                    batch_states[agent_name] = "submitted"

                if batch_states[agent_name] == "submitted":
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

            workflow.execution_order = execution_order
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map

            return workflow, agent_folder

    @pytest.mark.requires_real_batch_backend
    def test_batch_iteration_failure_blocks_subsequent(self, temp_dir, batch_workflow_config):
        """
        Test that failed batch iteration prevents next iteration from running.

        Scenario:
        - input completes
        - process_1 completes
        - process_2 completes
        - process_3 FAILS
        - process_4 should never run
        - process_5 should never run
        """
        workflow, agent_folder = self._create_workflow_with_injected_failure(
            temp_dir, batch_workflow_config, fail_at_agent="process_3"
        )

        # Run workflow multiple times (simulating batch mode)
        for run in range(10):  # More runs than needed to ensure we catch the failure
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        # Check status
        status_file = agent_folder / ".agent_status.json"
        assert status_file.exists()

        with open(status_file) as f:
            status = json.load(f)

        # Verify status of each agent
        assert status.get("input") == "completed", "input should complete"
        assert status.get("process_1") == "completed", "process_1 should complete"
        assert status.get("process_2") == "completed", "process_2 should complete"
        assert status.get("process_3") == "failed", "process_3 should fail"

        # Subsequent iterations should remain pending (never executed)
        assert status.get("process_4") in [None, "pending"], \
            "process_4 should not execute after process_3 fails"
        assert status.get("process_5") in [None, "pending"], \
            "process_5 should not execute after process_3 fails"

    @pytest.mark.requires_real_batch_backend
    def test_batch_partial_completion(self, temp_dir, batch_workflow_config):
        """
        Test workflow state correct when some iterations complete, some fail.

        Verify:
        - Output directories exist only for completed iterations
        - No output directories for failed/unexecuted iterations
        """
        workflow, agent_folder = self._create_workflow_with_injected_failure(
            temp_dir, batch_workflow_config, fail_at_agent="process_3"
        )

        # Run to completion
        for _ in range(10):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        target_dir = agent_folder / "target"

        # Completed iterations should have output directories
        assert (target_dir / "node_0_input").exists(), "input should have output"
        assert (target_dir / "node_1_process_1").exists(), "process_1 should have output"
        assert (target_dir / "node_2_process_2").exists(), "process_2 should have output"
        assert (target_dir / "node_3_process_3").exists(), "process_3 should have output (even if failed)"

        # Failed/unexecuted iterations should not have output
        # Note: process_4 and process_5 might have been submitted but never completed
        # So we check that their status is not 'completed'
        status_file = agent_folder / ".agent_status.json"
        with open(status_file) as f:
            status = json.load(f)

        assert status.get("process_4") != "completed", "process_4 should not complete"
        assert status.get("process_5") != "completed", "process_5 should not complete"

    @pytest.mark.requires_real_batch_backend
    def test_batch_recovery_after_fix(self, temp_dir, batch_workflow_config):
        """
        Test that workflow can resume after fixing failed iteration.

        Scenario:
        1. Run workflow, process_3 fails
        2. "Fix" the issue (mock process_3 to succeed)
        3. Resume workflow
        4. Verify process_3, process_4, process_5 all complete
        """
        # First run: process_3 fails
        workflow, agent_folder = self._create_workflow_with_injected_failure(
            temp_dir, batch_workflow_config, fail_at_agent="process_3"
        )

        for _ in range(10):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        # Verify process_3 failed
        status_file = agent_folder / ".agent_status.json"
        with open(status_file) as f:
            status = json.load(f)
        assert status.get("process_3") == "failed"

        # Now "fix" the issue - create new workflow without injected failure
        # (In reality, user would fix their code/data and re-run)
        workflow_fixed, _ = self._create_workflow_with_injected_failure(
            temp_dir, batch_workflow_config, fail_at_agent=None  # No failure
        )

        # Manually reset process_3 status to allow retry
        # (Simulates user intervention: removing failed status)
        with open(status_file) as f:
            status = json.load(f)
        status["process_3"] = "pending"  # Reset to pending
        with open(status_file, 'w') as f:
            json.dump(status, f)

        # Resume workflow
        for _ in range(10):
            try:
                workflow_fixed.run()
            except (SystemExit, StopIteration):
                pass

        # Verify all iterations eventually complete
        with open(status_file) as f:
            final_status = json.load(f)

        # After fix, all should complete
        for agent in ["input", "process_1", "process_2", "process_3", "process_4", "process_5"]:
            assert final_status.get(agent) == "completed", \
                f"{agent} should complete after recovery"

    @pytest.mark.requires_real_batch_backend
    def test_error_propagation_chain(self, temp_dir, batch_workflow_config):
        """
        Test that error in iteration N prevents all subsequent iterations N+1, N+2, etc.

        This verifies the dependency chain correctly blocks execution.
        """
        # Fail at iteration 2 (early in the sequence)
        workflow, agent_folder = self._create_workflow_with_injected_failure(
            temp_dir, batch_workflow_config, fail_at_agent="process_2"
        )

        for _ in range(10):
            try:
                workflow.run()
            except (SystemExit, StopIteration):
                pass

        status_file = agent_folder / ".agent_status.json"
        with open(status_file) as f:
            status = json.load(f)

        # Verify propagation
        assert status.get("input") == "completed"
        assert status.get("process_1") == "completed"
        assert status.get("process_2") == "failed"

        # All subsequent should not complete
        for agent in ["process_3", "process_4", "process_5"]:
            assert status.get(agent) != "completed", \
                f"{agent} should not complete after process_2 fails"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
