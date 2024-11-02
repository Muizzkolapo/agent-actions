import unittest
import os
import yaml
from unittest.mock import patch, mock_open, MagicMock
from agent_actions.core.init import create_directory, create_file, init_project

class TestAgentActionsProject(unittest.TestCase):

    @patch('agent_actions.project_initializer.os.makedirs')
    @patch('agent_actions.project_initializer.os.path.exists', return_value=False)
    @patch('agent_actions.project_initializer.logger')
    def test_create_directory_new(self, mock_logger, mock_exists, mock_makedirs):
        path = 'test_directory'
        create_directory(path)
        mock_makedirs.assert_called_once_with(path)
        mock_logger.debug.assert_called_with(f"Checking if directory exists: {path}")
        mock_logger.info.assert_called_with(f"Created directory: {path}")

    @patch('agent_actions.project_initializer.os.makedirs')
    @patch('agent_actions.project_initializer.os.path.exists', return_value=True)
    @patch('agent_actions.project_initializer.logger')
    def test_create_directory_existing(self, mock_logger, mock_exists, mock_makedirs):
        path = 'test_directory'
        create_directory(path)
        mock_makedirs.assert_not_called()
        mock_logger.debug.assert_called_with(f"Checking if directory exists: {path}")
        mock_logger.warning.assert_called_with(f"Directory already exists: {path}")

    @patch('builtins.open', new_callable=mock_open)
    @patch('agent_actions.project_initializer.os.path.exists', return_value=False)
    @patch('agent_actions.project_initializer.logger')
    def test_create_file_new(self, mock_logger, mock_exists, mock_open_file):
        path = 'test_file.txt'
        content = 'test content'
        create_file(path, content)
        mock_open_file.assert_called_once_with(path, 'w', encoding='utf-8')
        mock_open_file().write.assert_called_once_with(content)
        mock_logger.debug.assert_called_with(f"Checking if file exists: {path}")
        mock_logger.info.assert_called_with(f"Created file: {path}")

    @patch('builtins.open', new_callable=mock_open)
    @patch('agent_actions.project_initializer.os.path.exists', return_value=True)
    @patch('agent_actions.project_initializer.logger')
    def test_create_file_existing(self, mock_logger, mock_exists, mock_open_file):
        path = 'test_file.txt'
        create_file(path)
        mock_open_file.assert_not_called()
        mock_logger.debug.assert_called_with(f"Checking if file exists: {path}")
        mock_logger.warning.assert_called_with(f"File already exists: {path}")

    @patch('agent_actions.project_initializer.create_directory')
    @patch('agent_actions.project_initializer.create_file')
    @patch('agent_actions.project_initializer.logger')
    def test_init_project_successful(self, mock_logger, mock_create_file, mock_create_directory):
        project_name = 'test_project'
        init_project(project_name)

        # Define expected directory and file paths
        project_dir = os.path.join(os.getcwd(), project_name)
        config_dir = os.path.join(project_dir, 'agent_config')
        schema_dir = os.path.join(project_dir, 'schema')
        io_dir = os.path.join(project_dir, 'agent_io')
        config_file = os.path.join(project_dir, 'agent_actions.yml')
        
        # Check directory creation calls
        mock_create_directory.assert_any_call(project_dir)
        mock_create_directory.assert_any_call(config_dir)
        mock_create_directory.assert_any_call(schema_dir)
        mock_create_directory.assert_any_call(io_dir)

        # Check file creation call with YAML content
        config_data = {
            "default_agent_config": {
                "api_key": "OPENAI_API_KEY",
                "model_name": "gpt-3.5-turbo",
                "chunk_config": {
                    "chunk_size": 300,
                    "overlap": 10
                }
            }
        }
        mock_create_file.assert_called_once_with(config_file, yaml.dump(config_data))

        # Check logging calls for successful initialization
        mock_logger.info.assert_any_call(f"Initializing project '{project_name}'")
        mock_logger.debug.assert_any_call(f"Creating main project directory at {project_dir}")
        mock_logger.debug.assert_any_call("Creating configuration, schema, and I/O directories")
        mock_logger.debug.assert_any_call(f"Creating configuration file at {config_file}")
        mock_logger.info.assert_any_call(f"Project '{project_name}' initialized successfully.")

    @patch('agent_actions.project_initializer.create_directory')
    @patch('agent_actions.project_initializer.create_file', side_effect=Exception("File creation error"))
    @patch('agent_actions.project_initializer.logger')
    def test_init_project_failure(self, mock_logger, mock_create_file, mock_create_directory):
        project_name = 'test_project'
        init_project(project_name)

        # Ensure logging captures the critical failure
        mock_logger.info.assert_any_call(f"Initializing project '{project_name}'")
        mock_logger.critical.assert_called_with(
            f"Failed to initialize project '{project_name}': File creation error", exc_info=True
        )

if __name__ == '__main__':
    unittest.main()
