"""Tests for AgentWorkflow sequential loop execution."""
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from typing import Dict, List, Any
from agent_actions.orchestration.agent_workflow import AgentWorkflow

class TestAgentWorkflowSequentialLoops:
    """Test suite for sequential loop execution in AgentWorkflow."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def workflow_with_sequential_loop(self, temp_dir):
        """Create an AgentWorkflow with sequential loop configuration."""
        config_file = temp_dir / 'config.yml'
        config_data = {'name': 'sequential_test', 'execution_plan': ['input', 'refine_1', 'refine_2', 'refine_3', 'output'], 'actions': [{'name': 'input', 'tool': 'mock_tool'}, {'name': 'refine', 'tool': 'mock_tool', 'loop': {'param': 'stage', 'range': [1, 3], 'mode': 'sequential'}}, {'name': 'output', 'tool': 'mock_tool'}]}
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        with patch('agent_actions.orchestration.agent_workflow.ConfigManager') as MockConfigManager, patch('agent_actions.configuration.bootstrap_factory.create_agent_runner') as mock_create_runner, patch('agent_actions.orchestration.agent_workflow.OutputProcessor'), patch('agent_actions.orchestration.agent_workflow.BatchService'), patch('agent_actions.orchestration.agent_workflow.WhereClauseParser'), patch('agent_actions.orchestration.agent_workflow.ManifestArtifact'):
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {'input': {'agent_type': 'input', 'dependencies': [], 'loop_mode': None}, 'refine_1': {'agent_type': 'refine_1', 'dependencies': ['input'], 'is_loop_agent': True, 'loop_base_name': 'refine', 'loop_iteration': 1, 'loop_mode': 'sequential'}, 'refine_2': {'agent_type': 'refine_2', 'dependencies': ['refine_1'], 'is_loop_agent': True, 'loop_base_name': 'refine', 'loop_iteration': 2, 'loop_mode': 'sequential'}, 'refine_3': {'agent_type': 'refine_3', 'dependencies': ['refine_2'], 'is_loop_agent': True, 'loop_base_name': 'refine', 'loop_iteration': 3, 'loop_mode': 'sequential'}, 'output': {'agent_type': 'output', 'dependencies': ['refine_3'], 'loop_mode': None}}
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ['input', 'refine_1', 'refine_2', 'refine_3', 'output']
            mock_config_manager.run_id = 'test_run'
            mock_config_manager.agent_name = 'sequential_test'
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager
            mock_runner = MagicMock()
            mock_runner.get_agent_folder.return_value = str(temp_dir / 'agent_io')
            mock_create_runner.return_value = mock_runner
            workflow = AgentWorkflow(constructor_path=str(config_file), user_code_path=None, default_path=None, use_tools=True, parent_output=None, parent_source=None, parent_pipeline=None)
            workflow.execution_order = ['input', 'refine_1', 'refine_2', 'refine_3', 'output']
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map
            agent_folder = Path(mock_runner.get_agent_folder())
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / 'staging').mkdir(exist_ok=True)
            return workflow

    @pytest.fixture
    def workflow_with_parallel_loop(self, temp_dir):
        """Create an AgentWorkflow with parallel loop configuration for comparison."""
        config_file = temp_dir / 'config.yml'
        config_data = {'name': 'parallel_test', 'execution_plan': ['input', 'process_1', 'process_2', 'process_3', 'output'], 'actions': [{'name': 'input', 'tool': 'mock_tool'}, {'name': 'process', 'tool': 'mock_tool', 'loop': {'param': 'idx', 'range': [1, 3], 'mode': 'parallel'}}, {'name': 'output', 'tool': 'mock_tool'}]}
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        with patch('agent_actions.orchestration.agent_workflow.ConfigManager') as MockConfigManager, patch('agent_actions.configuration.bootstrap_factory.create_agent_runner') as mock_create_runner, patch('agent_actions.orchestration.agent_workflow.OutputProcessor'), patch('agent_actions.orchestration.agent_workflow.BatchService'), patch('agent_actions.orchestration.agent_workflow.WhereClauseParser'), patch('agent_actions.orchestration.agent_workflow.ManifestArtifact'):
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {'input': {'agent_type': 'input', 'dependencies': [], 'loop_mode': None}, 'process_1': {'agent_type': 'process_1', 'dependencies': ['input'], 'is_loop_agent': True, 'loop_base_name': 'process', 'loop_mode': 'parallel'}, 'process_2': {'agent_type': 'process_2', 'dependencies': ['input'], 'is_loop_agent': True, 'loop_base_name': 'process', 'loop_mode': 'parallel'}, 'process_3': {'agent_type': 'process_3', 'dependencies': ['input'], 'is_loop_agent': True, 'loop_base_name': 'process', 'loop_mode': 'parallel'}, 'output': {'agent_type': 'output', 'dependencies': ['process_1', 'process_2', 'process_3'], 'loop_mode': None}}
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ['input', 'process_1', 'process_2', 'process_3', 'output']
            mock_config_manager.run_id = 'test_run'
            mock_config_manager.agent_name = 'parallel_test'
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager
            mock_runner = MagicMock()
            mock_runner.get_agent_folder.return_value = str(temp_dir / 'agent_io')
            mock_create_runner.return_value = mock_runner
            workflow = AgentWorkflow(constructor_path=str(config_file), user_code_path=None, default_path=None, use_tools=True, parent_output=None, parent_source=None, parent_pipeline=None)
            workflow.execution_order = ['input', 'process_1', 'process_2', 'process_3', 'output']
            workflow.agent_configs = mock_config_manager.agent_configs
            workflow.agent_config_map = mock_config_manager.agent_config_map
            agent_folder = Path(mock_runner.get_agent_folder())
            agent_folder.mkdir(parents=True, exist_ok=True)
            (agent_folder / 'staging').mkdir(exist_ok=True)
            return workflow

    def test_sequential_loop_has_correct_dependencies(self, workflow_with_sequential_loop):
        """Test that sequential loop iterations have chained dependencies."""
        configs = workflow_with_sequential_loop.agent_configs
        assert configs['refine_1']['dependencies'] == ['input']
        assert configs['refine_2']['dependencies'] == ['refine_1']
        assert configs['refine_3']['dependencies'] == ['refine_2']
        assert configs['output']['dependencies'] == ['refine_3']
        assert configs['refine_1']['loop_mode'] == 'sequential'
        assert configs['refine_2']['loop_mode'] == 'sequential'
        assert configs['refine_3']['loop_mode'] == 'sequential'

    def test_parallel_loop_has_independent_dependencies(self, workflow_with_parallel_loop):
        """Test that parallel loop iterations have independent dependencies."""
        configs = workflow_with_parallel_loop.agent_configs
        assert configs['process_1']['dependencies'] == ['input']
        assert configs['process_2']['dependencies'] == ['input']
        assert configs['process_3']['dependencies'] == ['input']
        assert configs['process_1']['loop_mode'] == 'parallel'
        assert configs['process_2']['loop_mode'] == 'parallel'
        assert configs['process_3']['loop_mode'] == 'parallel'

    def test_sequential_execution_order_enforced(self, workflow_with_sequential_loop):
        """Test that execution order enforces sequential iteration execution."""
        execution_order = workflow_with_sequential_loop.execution_order
        assert execution_order == ['input', 'refine_1', 'refine_2', 'refine_3', 'output']
        assert execution_order.index('refine_1') < execution_order.index('refine_2')
        assert execution_order.index('refine_2') < execution_order.index('refine_3')

    def test_iteration_can_access_previous_output_directory(self, workflow_with_sequential_loop):
        """Test that iteration N+1 can locate iteration N's output directory."""
        agent_folder = Path(workflow_with_sequential_loop.agent_runner.get_agent_folder())
        (agent_folder / 'target' / 'node_0_input').mkdir(parents=True, exist_ok=True)
        (agent_folder / 'target' / 'node_1_refine_1').mkdir(parents=True, exist_ok=True)
        (agent_folder / 'target' / 'node_2_refine_2').mkdir(parents=True, exist_ok=True)
        input_dir = workflow_with_sequential_loop._get_input_directory(2)
        assert 'node_1_refine_1' in input_dir
        input_dir = workflow_with_sequential_loop._get_input_directory(3)
        assert 'node_2_refine_2' in input_dir

    def test_error_in_iteration_prevents_subsequent_execution(self, workflow_with_sequential_loop):
        """Test that error in iteration N prevents iteration N+1 from executing."""
        configs = workflow_with_sequential_loop.agent_configs
        assert 'refine_1' in configs['refine_2']['dependencies']
        assert 'refine_2' in configs['refine_3']['dependencies']

    def test_sequential_loop_metadata_preserved(self, workflow_with_sequential_loop):
        """Test that sequential loop metadata is preserved in agent configs."""
        configs = workflow_with_sequential_loop.agent_configs
        for agent_name in ['refine_1', 'refine_2', 'refine_3']:
            agent_config = configs[agent_name]
            assert agent_config['is_loop_agent'] is True
            assert agent_config['loop_base_name'] == 'refine'
            assert 'loop_iteration' in agent_config
            assert agent_config['loop_mode'] == 'sequential'

    def test_mixed_sequential_and_non_loop_agents(self, workflow_with_sequential_loop):
        """Test workflow with both sequential loop and non-loop agents."""
        configs = workflow_with_sequential_loop.agent_configs
        assert configs['input'].get('loop_mode') is None
        assert configs['output'].get('loop_mode') is None
        assert configs['refine_1']['loop_mode'] == 'sequential'
        assert configs['refine_2']['loop_mode'] == 'sequential'
        assert configs['refine_3']['loop_mode'] == 'sequential'

    def test_first_iteration_inherits_original_dependencies(self, workflow_with_sequential_loop):
        """Test that first iteration in sequential loop keeps original dependencies."""
        configs = workflow_with_sequential_loop.agent_configs
        assert configs['refine_1']['dependencies'] == ['input']
        assert 'refine_0' not in configs

    def test_sequential_loop_with_single_iteration(self, temp_dir):
        """Test sequential loop with only one iteration behaves correctly."""
        config_file = temp_dir / 'config.yml'
        config_data = {'name': 'single_iteration_test', 'execution_plan': ['input', 'process_1', 'output'], 'actions': [{'name': 'input', 'tool': 'mock_tool'}, {'name': 'process', 'tool': 'mock_tool', 'loop': {'param': 'i', 'range': [1, 1], 'mode': 'sequential'}}, {'name': 'output', 'tool': 'mock_tool'}]}
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        with patch('agent_actions.orchestration.agent_workflow.ConfigManager') as MockConfigManager, patch('agent_actions.configuration.bootstrap_factory.create_agent_runner') as mock_create_runner, patch('agent_actions.orchestration.agent_workflow.OutputProcessor'), patch('agent_actions.orchestration.agent_workflow.BatchService'), patch('agent_actions.orchestration.agent_workflow.WhereClauseParser'), patch('agent_actions.orchestration.agent_workflow.ManifestArtifact'):
            mock_config_manager = MagicMock()
            mock_config_manager.agent_configs = {'input': {'agent_type': 'input', 'dependencies': []}, 'process_1': {'agent_type': 'process_1', 'dependencies': ['input'], 'is_loop_agent': True, 'loop_base_name': 'process', 'loop_iteration': 1, 'loop_mode': 'sequential'}, 'output': {'agent_type': 'output', 'dependencies': ['process_1']}}
            mock_config_manager.agent_config_map = MagicMock(agent_configs=mock_config_manager.agent_configs)
            mock_config_manager.execution_order = ['input', 'process_1', 'output']
            mock_config_manager.run_id = 'test_run'
            mock_config_manager.agent_name = 'single_iteration_test'
            mock_config_manager.tool_path = []
            MockConfigManager.return_value = mock_config_manager
            mock_runner = MagicMock()
            mock_runner.get_agent_folder.return_value = str(temp_dir / 'agent_io')
            mock_create_runner.return_value = mock_runner
            workflow = AgentWorkflow(constructor_path=str(config_file), user_code_path=None, default_path=None, use_tools=True, parent_output=None, parent_source=None, parent_pipeline=None)
            workflow.execution_order = ['input', 'process_1', 'output']
            workflow.agent_configs = mock_config_manager.agent_configs
            assert workflow.agent_configs['process_1']['dependencies'] == ['input']
            assert workflow.agent_configs['process_1']['loop_mode'] == 'sequential'
if __name__ == '__main__':
    pytest.main([__file__, '-v'])