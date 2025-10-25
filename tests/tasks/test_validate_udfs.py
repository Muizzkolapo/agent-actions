"""Tests for validate-udfs CLI command."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
import tempfile
import shutil
import yaml
from agent_actions.validation.validate_udfs import validate_udfs_cmd
from agent_actions.utilities.udf_registry import clear_registry

@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clear registry before and after each test."""
    clear_registry()
    yield
    clear_registry()

@pytest.fixture
def temp_user_code_dir():
    """Create a temporary directory for user code."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory with config."""
    temp_dir = tempfile.mkdtemp()
    project_path = Path(temp_dir)
    agent_configs_dir = project_path / 'agent_configs'
    agent_configs_dir.mkdir()
    agent_io_dir = project_path / 'agent_io'
    agent_io_dir.mkdir()
    yield (project_path, agent_configs_dir, agent_io_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()

class TestValidateUDFsCommand:
    """Tests for validate-udfs command."""

    @patch('agent_actions.validation.validate_udfs.ProjectPathsFactory.create_project_paths')
    @patch('agent_actions.validation.validate_udfs.ConfigManager')
    def test_validate_udfs_success(self, mock_config_manager, mock_paths, runner, temp_user_code_dir, temp_project_dir):
        """Test validate-udfs with valid UDF references."""
        project_path, agent_configs_dir, agent_io_dir = temp_project_dir
        udf_file = temp_user_code_dir / 'functions.py'
        udf_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef valid_function():\n    return "valid"\n')
        config_file = agent_configs_dir / 'test_agent.yml'
        config = {'actions': [{'name': 'action1', 'impl': 'valid_function'}]}
        config_file.write_text(yaml.dump(config))
        mock_path_obj = MagicMock()
        mock_path_obj.agent_config_dir = agent_configs_dir
        mock_path_obj.default_config_path = agent_io_dir / 'default.yml'
        mock_paths.return_value = mock_path_obj
        mock_cm = MagicMock()
        mock_cm.config = config
        mock_config_manager.return_value = mock_cm
        result = runner.invoke(validate_udfs_cmd, ['-a', 'test_agent', '-u', str(temp_user_code_dir)])
        assert result.exit_code == 0
        assert '🔍 Discovering UDFs' in result.output
        assert '✅ Discovered 1 UDF(s)' in result.output
        assert '✅ All UDF references valid' in result.output
        assert '1 UDF(s) referenced' in result.output

    @patch('agent_actions.validation.validate_udfs.ProjectPathsFactory.create_project_paths')
    @patch('agent_actions.validation.validate_udfs.ConfigManager')
    def test_validate_udfs_missing_function(self, mock_config_manager, mock_paths, runner, temp_user_code_dir, temp_project_dir):
        """Test validate-udfs detects missing function reference."""
        project_path, agent_configs_dir, agent_io_dir = temp_project_dir
        udf_file = temp_user_code_dir / 'functions.py'
        udf_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef existing_function():\n    return "exists"\n')
        config_file = agent_configs_dir / 'test_agent.yml'
        config = {'actions': [{'name': 'action1', 'impl': 'nonexistent_function'}]}
        config_file.write_text(yaml.dump(config))
        mock_path_obj = MagicMock()
        mock_path_obj.agent_config_dir = agent_configs_dir
        mock_path_obj.default_config_path = agent_io_dir / 'default.yml'
        mock_paths.return_value = mock_path_obj
        mock_cm = MagicMock()
        mock_cm.config = config
        mock_config_manager.return_value = mock_cm
        result = runner.invoke(validate_udfs_cmd, ['-a', 'test_agent', '-u', str(temp_user_code_dir)])
        assert "❌ Function 'nonexistent_function' not found" in result.output
        assert 'existing_function' in result.output

    @patch('agent_actions.validation.validate_udfs.ProjectPathsFactory.create_project_paths')
    def test_validate_udfs_duplicate_function(self, mock_paths, runner, temp_user_code_dir, temp_project_dir):
        """Test validate-udfs detects duplicate function names."""
        project_path, agent_configs_dir, agent_io_dir = temp_project_dir
        file1 = temp_user_code_dir / 'file1.py'
        file1.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef duplicate_func():\n    return "file1"\n')
        file2 = temp_user_code_dir / 'file2.py'
        file2.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef duplicate_func():\n    return "file2"\n')
        config_file = agent_configs_dir / 'test_agent.yml'
        config = {'actions': []}
        config_file.write_text(yaml.dump(config))
        mock_path_obj = MagicMock()
        mock_path_obj.agent_config_dir = agent_configs_dir
        mock_path_obj.default_config_path = agent_io_dir / 'default.yml'
        mock_paths.return_value = mock_path_obj
        result = runner.invoke(validate_udfs_cmd, ['-a', 'test_agent', '-u', str(temp_user_code_dir)])
        assert "❌ Error: Duplicate function name 'duplicate_func'" in result.output
        assert 'First definition' in result.output
        assert 'Duplicate definition' in result.output

    @patch('agent_actions.validation.validate_udfs.ProjectPathsFactory.create_project_paths')
    def test_validate_udfs_import_error(self, mock_paths, runner, temp_user_code_dir, temp_project_dir):
        """Test validate-udfs handles import errors gracefully."""
        project_path, agent_configs_dir, agent_io_dir = temp_project_dir
        bad_file = temp_user_code_dir / 'bad_syntax.py'
        bad_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef bad_function()  # Missing colon\n    return "bad"\n')
        config_file = agent_configs_dir / 'test_agent.yml'
        config = {'actions': []}
        config_file.write_text(yaml.dump(config))
        mock_path_obj = MagicMock()
        mock_path_obj.agent_config_dir = agent_configs_dir
        mock_path_obj.default_config_path = agent_io_dir / 'default.yml'
        mock_paths.return_value = mock_path_obj
        result = runner.invoke(validate_udfs_cmd, ['-a', 'test_agent', '-u', str(temp_user_code_dir)])
        assert '❌ Error loading UDF module' in result.output or result.exit_code != 0

    @patch('agent_actions.validation.validate_udfs.ProjectPathsFactory.create_project_paths')
    @patch('agent_actions.validation.validate_udfs.ConfigManager')
    def test_validate_udfs_output_formatting(self, mock_config_manager, mock_paths, runner, temp_user_code_dir, temp_project_dir):
        """Test validate-udfs output formatting and summary."""
        project_path, agent_configs_dir, agent_io_dir = temp_project_dir
        udf_file = temp_user_code_dir / 'processors.py'
        udf_file.write_text('\nfrom agent_actions import udf_tool\n\n@udf_tool\ndef process_data():\n    return "processed"\n\n@udf_tool\ndef validate_data():\n    return "validated"\n')
        config_file = agent_configs_dir / 'test_agent.yml'
        config = {'actions': [{'name': 'action1', 'impl': 'process_data'}]}
        config_file.write_text(yaml.dump(config))
        mock_path_obj = MagicMock()
        mock_path_obj.agent_config_dir = agent_configs_dir
        mock_path_obj.default_config_path = agent_io_dir / 'default.yml'
        mock_paths.return_value = mock_path_obj
        mock_cm = MagicMock()
        mock_cm.config = config
        mock_config_manager.return_value = mock_cm
        result = runner.invoke(validate_udfs_cmd, ['-a', 'test_agent', '-u', str(temp_user_code_dir)])
        assert result.exit_code == 0
        assert 'Summary:' in result.output
        assert '1 UDF(s) referenced in config' in result.output
        assert '2 UDF(s) discovered' in result.output
        assert 'Referenced UDFs:' in result.output
        assert 'process_data' in result.output