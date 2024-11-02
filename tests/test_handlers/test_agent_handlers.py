import unittest
from unittest.mock import patch, MagicMock
from agent_actions.handlers.agent_handlers import AgentManager, SchemaLoader, PromptLoader

class TestAgentManager(unittest.TestCase):

    @patch('agent_actions.agent_manager.logger')
    @patch('agent_actions.agent_manager.FileHandler.find_specific_folder', return_value=None)
    def test_clean_agent_directories_not_found(self, mock_find_folder, mock_logger):
        AgentManager.clean_agent_directories("nonexistent_agent")
        mock_logger.warning.assert_called_with("Agent folder not found for agent: nonexistent_agent")

    @patch('agent_actions.agent_manager.logger')
    @patch('agent_actions.agent_manager.FileHandler.find_specific_folder', return_value="mock_folder")
    @patch('agent_actions.agent_manager.os.path.exists', return_value=True)
    @patch('agent_actions.agent_manager.shutil.rmtree')
    def test_clean_agent_directories_success(self, mock_rmtree, mock_exists, mock_find_folder, mock_logger):
        AgentManager.clean_agent_directories("test_agent")
        mock_logger.info.assert_any_call("Deleted directory: mock_folder/staging")
        mock_rmtree.assert_called()

class TestSchemaLoader(unittest.TestCase):

    @patch('agent_actions.agent_manager.logger')
    @patch('agent_actions.agent_manager.FileHandler.find_file_in_directory', return_value=None)
    def test_load_schema_not_found(self, mock_find_file, mock_logger):
        result = SchemaLoader.load_schema("nonexistent_schema")
        self.assertIsNone(result)
        mock_logger.error.assert_called_with("Schema file or directory not found: Schema file not found: nonexistent_schema.yml", exc_info=True)

class TestPromptLoader(unittest.TestCase):

    @patch('agent_actions.agent_manager.logger')
    @patch('agent_actions.agent_manager.FileHandler.find_file_in_directory', return_value="mock_file.md")
    @patch('agent_actions.agent_manager.PromptLoader.extract_prompt', return_value="Sample prompt content")
    def test_load_prompt_success(self, mock_extract_prompt, mock_find_file, mock_logger):
        prompt = PromptLoader.load_prompt("mock_file.sample_prompt")
        self.assertEqual(prompt, "Sample prompt content")
        mock_logger.info.assert_called_with("Prompt 'mock_file.sample_prompt' loaded successfully")

if __name__ == '__main__':
    unittest.main()
