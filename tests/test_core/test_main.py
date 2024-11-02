import unittest
from unittest.mock import patch, MagicMock
from agent_actions.core.main import main, init, docs, run, clean

class TestAgentActionsCLI(unittest.TestCase):

    @patch('agent_actions.cli.init_project')
    @patch('agent_actions.cli.logger')
    def test_init_command_success(self, mock_logger, mock_init_project):
        runner = main.make_context("init", ["test_project"])
        init.callback(runner, project_name="test_project")
        mock_init_project.assert_called_once_with("test_project")
        mock_logger.info.assert_any_call("Starting project initialization for 'test_project'")
        mock_logger.info.assert_any_call("Project 'test_project' initialized successfully")

    @patch('agent_actions.cli.run_app')
    @patch('agent_actions.cli.logger')
    def test_docs_command_success(self, mock_logger, mock_run_app):
        runner = main.make_context("docs", ["--host", "127.0.0.1", "--port", "5000", "--debug"])
        docs.callback(runner, host="127.0.0.1", port=5000, debug=True)
        mock_run_app.assert_called_once_with("127.0.0.1", 5000, True)
        mock_logger.info.assert_any_call("Starting documentation server")
        mock_logger.debug.assert_called_with("Server running on host 127.0.0.1 and port 5000, debug=True")

    @patch('agent_actions.cli.run_agent_workflow')
    @patch('agent_actions.cli.FileHandler.get_agent_paths', return_value=("config_dir", "io_dir", "log_dir"))
    @patch('agent_actions.cli.ConfigValidator.check_agent_file_unique', return_value=True)
    @patch('agent_actions.cli.ConfigValidator.check_agent_name_unique', return_value=True)
    @patch('agent_actions.cli.logger')
    def test_run_command_success(self, mock_logger, mock_check_name_unique, mock_check_file_unique, mock_get_paths, mock_run_workflow):
        runner = main.make_context("run", ["--agent", "test_agent"])
        run.callback(runner, agent="test_agent", user_code=None)
        mock_run_workflow.assert_called_once()
        mock_logger.info.assert_any_call("Starting agent run for 'test_agent'")
        mock_logger.info.assert_any_call("Agent workflow for 'test_agent' completed successfully")

    @patch('agent_actions.cli.AgentManager.clean_agent_directories')
    @patch('agent_actions.cli.logger')
    def test_clean_command_success(self, mock_logger, mock_clean_directories):
        runner = main.make_context("clean", ["--agent", "test_agent"])
        clean.callback(runner, agent="test_agent")
        mock_clean_directories.assert_called_once_with("test_agent")
        mock_logger.info.assert_any_call("Cleaning directories for agent 'test_agent'")
        mock_logger.info.assert_any_call("Directories for agent 'test_agent' cleaned successfully")

if __name__ == '__main__':
    unittest.main()
