import unittest
from unittest.mock import patch, MagicMock
from agent_actions.handlers.config_handler import ConfigValidator

class TestConfigValidator(unittest.TestCase):

    @patch('agent_actions.config_validator.logger')
    def test_validate_agent_config_success(self, mock_logger):
        agent_config = [
            {
                'agent_type': 'text',
                'model_name': 'gpt-3.5',
                'api_key': 'sample_key',
                'schema_name': 'sample_schema',
                'prompt': 'sample_prompt'
            }
        ]
        is_valid, message = ConfigValidator.validate_agent_config(agent_config)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Agent configuration is valid.")
        mock_logger.info.assert_called_with("Agent configuration validation completed successfully")

    @patch('agent_actions.config_validator.logger')
    def test_validate_agent_config_missing_keys(self, mock_logger):
        agent_config = [
            {
                'agent_type': 'text',
                'model_name': 'gpt-3.5'
                # Missing 'api_key', 'schema_name', and 'prompt'
            }
        ]
        is_valid, message = ConfigValidator.validate_agent_config(agent_config)
        self.assertFalse(is_valid)
        self.assertIn("missing required keys", message)
        mock_logger.error.assert_called()

    @patch('agent_actions.config_validator.logger')
    def test_validate_agent_config_invalid_dependencies_type(self, mock_logger):
        agent_config = [
            {
                'agent_type': 'text',
                'model_name': 'gpt-3.5',
                'api_key': 'sample_key',
                'schema_name': 'sample_schema',
                'prompt': 'sample_prompt',
                'dependencies': 'should be a list'
            }
        ]
        is_valid, message = ConfigValidator.validate_agent_config(agent_config)
        self.assertFalse(is_valid)
        self.assertIn("dependencies should be a list", message)
        mock_logger.error.assert_called_with("Agent 1: 'dependencies' should be a list.")

    @patch('agent_actions.config_validator.logger')
    def test_should_update_schema(self, mock_logger):
        agent_config = {'agent_type': 'text'}
        keys_list = ['text']
        side_collection = {'text': True}
        result = ConfigValidator.should_update_schema(agent_config, keys_list, side_collection)
        self.assertTrue(result)
        mock_logger.debug.assert_called_with("Schema update check for agent 'text' returned True")

    @patch('agent_actions.config_validator.FileHandler.get_all_agent_paths', return_value=["/path/to/agent1.yml", "/path/to/agent2.yml"])
    @patch('agent_actions.config_validator.logger')
    def test_check_agent_name_unique(self, mock_logger, mock_get_paths):
        base_dir = "/path/to"
        agent_name = "agent1"
        result = ConfigValidator.check_agent_name_unique(agent_name, base_dir)
        self.assertFalse(result)
        mock_logger.debug.assert_called_with("Agent name 'agent1' uniqueness check returned False")

    @patch('agent_actions.config_validator.FileHandler.get_all_agent_paths', return_value=["/path/to/agent1.yml", "/path/to/agent2.yml"])
    @patch('agent_actions.config_validator.logger')
    def test_check_agent_file_unique(self, mock_logger, mock_get_paths):
        base_dir = "/path/to"
        full_path = "/path/to/agent1.yml"
        result = ConfigValidator.check_agent_file_unique(full_path, base_dir)
        self.assertFalse(result)
        mock_logger.debug.assert_called_with("Configuration file path '/path/to/agent1.yml' uniqueness check returned False")

    @patch('agent_actions.config_validator.logger')
    def test_find_agent_name(self, mock_logger):
        config = {"agent_name": {}}
        result = ConfigValidator.find_agent_name(config)
        self.assertEqual(result, "agent_name")
        mock_logger.info.assert_called_with("Found agent name: agent_name")

if __name__ == '__main__':
    unittest.main()
