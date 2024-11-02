import unittest
from unittest.mock import patch, mock_open, MagicMock
import logging
import os
import json

# Import the functions from your 'agent_runners' module
from agent_actions.core.agent_runners  import (
    load_configs,
    validate_agent_name,
    check_child_pipeline,
    get_user_agents,
    merge_agent_configs,
    determine_execution_order,
    copy_parent_output_to_child_staging,
    copy_parent_source_to_child_source,
    run_agent,
    run_agent_workflow,
    merge_json_files,
    process_final_output,
    execute_child_pipeline
)

class TestAgentWorkflow(unittest.TestCase):

    @patch('builtins.open', new_callable=mock_open, read_data='agent_name:\n  agents: []')
    @patch('yaml.safe_load')
    def test_load_configs(self, mock_yaml_load, mock_file):
        mock_yaml_load.side_effect = [{'user_config_key': 'user_config_value'}, {'default_config_key': 'default_config_value'}]
        user_config, default_config = load_configs('constructor_path.yml', 'default_path.yml')
        self.assertEqual(user_config, {'user_config_key': 'user_config_value'})
        self.assertEqual(default_config, {'default_config_key': 'default_config_value'})

    def test_validate_agent_name_success(self):
        agent_name = 'agent1'
        constructor_path = '/path/to/agent1.yml'
        # Should not raise an error
        validate_agent_name(agent_name, constructor_path)

    def test_validate_agent_name_failure(self):
        agent_name = 'agent2'
        constructor_path = '/path/to/agent1.yml'
        with self.assertRaises(ValueError):
            validate_agent_name(agent_name, constructor_path)

    def test_check_child_pipeline_found(self):
        user_config = {'agent_name': [{'child': ['child_pipeline_name']}]}
        agent_name = 'agent_name'
        result = check_child_pipeline(user_config, agent_name)
        self.assertEqual(result, 'child_pipeline_name')

    def test_check_child_pipeline_not_found(self):
        user_config = {'agent_name': [{'agent_type': 'type1'}]}
        agent_name = 'agent_name'
        result = check_child_pipeline(user_config, agent_name)
        self.assertIsNone(result)

    def test_get_user_agents_with_agents_key(self):
        user_config = {'agent_name': {'agents': ['agent1', 'agent2']}}
        agent_name = 'agent_name'
        result = get_user_agents(user_config, agent_name)
        self.assertEqual(result, ['agent1', 'agent2'])

    def test_get_user_agents_without_agents_key(self):
        user_config = {'agent_name': [{'agent_type': 'type1'}, {'agent_type': 'type2'}]}
        agent_name = 'agent_name'
        result = get_user_agents(user_config, agent_name)
        self.assertEqual(result, [{'agent_type': 'type1'}, {'agent_type': 'type2'}])

    def test_merge_agent_configs(self):
        user_agents = [{'agent_type': 'type1', 'config1': 'value1'}, {'agent_type': 'type2', 'config2': 'value2'}]
        default_agent_config = {'default_key': 'default_value'}
        result = merge_agent_configs(user_agents, default_agent_config)
        expected = {
            'type1': {'default_key': 'default_value', 'agent_type': 'type1', 'config1': 'value1'},
            'type2': {'default_key': 'default_value', 'agent_type': 'type2', 'config2': 'value2'}
        }
        self.assertEqual(result, expected)

    @patch('agent_actions.core.utils.Utils.topological_sort')
    def test_determine_execution_order(self, mock_topological_sort):
        user_agents = [{'agent_type': 'type1', 'dependencies': []}, {'agent_type': 'type2', 'dependencies': ['type1']}]
        mock_topological_sort.return_value = ['type1', 'type2']
        result = determine_execution_order(user_agents)
        self.assertEqual(result, ['type1', 'type2'])
        mock_topological_sort.assert_called_once()

    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('os.listdir')
    @patch('shutil.copy')
    def test_copy_parent_output_to_child_staging(self, mock_copy, mock_listdir, mock_exists, mock_makedirs):
        mock_exists.return_value = True
        mock_listdir.return_value = ['file1', 'file2']
        parent_output = '/parent/output'
        child_base_dir = '/child/base'
        copy_parent_output_to_child_staging(parent_output, child_base_dir)
        mock_makedirs.assert_called_once_with(os.path.join(child_base_dir, 'staging'), exist_ok=True)
        calls = [patch.call(os.path.join(parent_output, 'file1'), os.path.join(child_base_dir, 'staging')),
                 patch.call(os.path.join(parent_output, 'file2'), os.path.join(child_base_dir, 'staging'))]
        mock_copy.assert_has_calls(calls, any_order=True)

    @patch('agent_actions.handlers.agent_handlers.AgentManager.process_and_generate_for_agent')
    def test_run_agent(self, mock_process_and_generate_for_agent):
        agent_config = {'agent_type': 'type1'}
        agent_name = 'workflow1'
        previous_agent_type = None
        idx = 0
        total_agents = 1
        use_tools = False

        # Mock the output folder returned by process_and_generate_for_agent
        mock_process_and_generate_for_agent.return_value = '/path/to/output'

        output_folder = run_agent(agent_config, agent_name, previous_agent_type, idx, total_agents, use_tools)
        self.assertEqual(output_folder, '/path/to/output')
        mock_process_and_generate_for_agent.assert_called_once()

    # Similar tests can be written for other functions like process_final_output, execute_child_pipeline, etc.

if __name__ == '__main__':
    unittest.main()
