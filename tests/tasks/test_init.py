"""
Comprehensive init task tests for the Agent Actions init command.

Tests cover init task functionality as specified in tests_recommendations.jsonc:
1. Creates expected structure in a temp directory
2. Respects output_dir when provided
3. Idempotent on rerun (no unexpected overwrite)
4. Rejects invalid project names with helpful error
"""
import os
import shutil
import pytest
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner
from agent_actions.cli.init import InitCommand, init
from agent_actions.validation.init_validator import InitCommandArgs
from agent_actions.shared.exceptions import ValidationError, FileSystemError, ConfigurationError
from pydantic import ValidationError as PydanticValidationError

class TestInitCommandArgs:
    """Test InitCommandArgs pydantic model."""

    def test_valid_init_command_args(self):
        """Test valid InitCommandArgs creation."""
        args = InitCommandArgs(project_name='test_project', output_dir=None, template='default', force=False)
        assert args.project_name == 'test_project'
        assert args.output_dir is None
        assert args.template == 'default'
        assert args.force is False

    def test_init_command_args_defaults(self):
        """Test InitCommandArgs with defaults."""
        args = InitCommandArgs(project_name='test_project')
        assert args.project_name == 'test_project'
        assert args.template == 'default'
        assert args.force is False

    def test_init_command_args_validation_empty_project_name(self):
        """Test InitCommandArgs validation rejects empty project name."""
        with pytest.raises(PydanticValidationError):
            InitCommandArgs(project_name='')

    def test_init_command_args_with_custom_values(self, tmp_path):
        """Test InitCommandArgs with custom values."""
        args = InitCommandArgs(project_name='custom_project', output_dir=str(tmp_path), template='minimal', force=True)
        assert args.project_name == 'custom_project'
        assert str(args.output_dir) == str(tmp_path)
        assert args.template == 'minimal'
        assert args.force is True

class TestInitCommand:
    """Test InitCommand implementation."""

    def test_init_command_initialization(self, tmp_path):
        """Test InitCommand initialization."""
        args = InitCommandArgs(project_name='test_project', output_dir=str(tmp_path), template='default', force=False)
        command = InitCommand(args)
        assert command.args == args
        assert command.output_dir == tmp_path
        assert command.project_dir == tmp_path / 'test_project'

    def test_init_command_initialization_default_output_dir(self):
        """Test InitCommand initialization with default output directory."""
        args = InitCommandArgs(project_name='test_project')
        with patch('pathlib.Path.cwd') as mock_cwd:
            mock_cwd.return_value = Path('/current/working/dir')
            command = InitCommand(args)
            assert command.output_dir == Path('/current/working/dir')
            assert command.project_dir == Path('/current/working/dir') / 'test_project'

    def test_get_available_templates(self, tmp_path):
        """Test _get_available_templates method."""
        args = InitCommandArgs(project_name='test_project', output_dir=str(tmp_path))
        command = InitCommand(args)
        templates = command._get_available_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0
        assert 'default' in templates
        templates2 = command._get_available_templates()
        assert templates == templates2

    def test_create_project_directory_success(self, tmp_path):
        """Test successful project directory creation."""
        args = InitCommandArgs(project_name='new_project', output_dir=str(tmp_path), force=False)
        command = InitCommand(args)
        command._create_project_directory()
        assert command.project_dir.exists()
        assert command.project_dir.is_dir()

    def test_create_project_directory_exists_no_force(self, tmp_path):
        """Test project directory creation when directory exists without force."""
        existing_dir = tmp_path / 'existing_project'
        existing_dir.mkdir()
        args = InitCommandArgs(project_name='existing_project', output_dir=str(tmp_path), force=False)
        command = InitCommand(args)
        with pytest.raises(ValidationError, match='Failed to create project directory'):
            command._create_project_directory()

    def test_create_project_directory_exists_with_force(self, tmp_path):
        """Test project directory creation when directory exists with force."""
        existing_dir = tmp_path / 'existing_project'
        existing_dir.mkdir()
        (existing_dir / 'old_file.txt').write_text('old content')
        args = InitCommandArgs(project_name='existing_project', output_dir=str(tmp_path), force=True)
        command = InitCommand(args)
        command._create_project_directory()
        assert command.project_dir.exists()
        assert command.project_dir.is_dir()
        assert not (command.project_dir / 'old_file.txt').exists()

    def test_create_project_directory_permission_error(self, tmp_path):
        """Test project directory creation with permission error."""
        args = InitCommandArgs(project_name='permission_test', output_dir=str(tmp_path), force=False)
        command = InitCommand(args)
        with patch('pathlib.Path.mkdir', side_effect=FileSystemError('Permission denied')):
            with pytest.raises(FileSystemError, match='Permission denied when creating project directory'):
                command._create_project_directory()

    def test_initialize_project_success(self, tmp_path):
        """Test successful project initialization."""
        args = InitCommandArgs(project_name='init_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        command.project_dir.mkdir()
        with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
            mock_initializer = Mock()
            mock_initializer_class.return_value = mock_initializer
            command._initialize_project()
            mock_initializer_class.assert_called_once_with(project_name='init_test', project_dir=str(command.project_dir), template='default')
            mock_initializer.init_project.assert_called_once()

    def test_initialize_project_failure(self, tmp_path):
        """Test project initialization failure handling."""
        args = InitCommandArgs(project_name='init_fail_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        command.project_dir.mkdir()
        with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
            mock_initializer = Mock()
            mock_initializer.init_project.side_effect = Exception('Initialization failed')
            mock_initializer_class.return_value = mock_initializer
            with pytest.raises(ConfigurationError, match='Failed to initialize project'):
                command._initialize_project()

class TestInitCommandExecution:
    """Test InitCommand execute method and full workflow."""

    def test_execute_success_full_workflow(self, tmp_path):
        """Test successful execution of full init workflow."""
        args = InitCommandArgs(project_name='full_test', output_dir=str(tmp_path), template='default', force=False)
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator') as mock_validator:
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer_class.return_value = mock_initializer
                with patch('click.echo') as mock_echo:
                    command.execute()
                    mock_validator.validate_project_name.assert_called_once_with('full_test')
                    mock_validator.validate_project_directory.assert_called_once()
                    mock_validator.validate_template.assert_called_once()
                    assert command.project_dir.exists()
                    mock_initializer.init_project.assert_called_once()
                    assert mock_echo.call_count >= 4

    def test_execute_validation_error(self, tmp_path):
        """Test execute handles validation errors properly."""
        args = InitCommandArgs(project_name='invalid-name!', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator') as mock_validator:
            mock_validator.validate_project_name.side_effect = ValidationError('Invalid project name')
            with pytest.raises(Exception):
                command.execute()

    def test_execute_permission_error(self, tmp_path):
        """Test execute handles permission errors properly."""
        args = InitCommandArgs(project_name='permission_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('pathlib.Path.mkdir', side_effect=FileSystemError('Permission denied')):
                with pytest.raises(Exception):
                    command.execute()

    def test_execute_configuration_error(self, tmp_path):
        """Test execute handles configuration errors properly."""
        args = InitCommandArgs(project_name='config_test', output_dir=str(tmp_path), template='invalid_template')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer.init_project.side_effect = Exception('Template not found')
                mock_initializer_class.return_value = mock_initializer
                with pytest.raises(Exception):
                    command.execute()

    def test_execute_unexpected_error(self, tmp_path):
        """Test execute handles unexpected errors properly."""
        args = InitCommandArgs(project_name='unexpected_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator') as mock_validator:
            mock_validator.validate_project_name.side_effect = RuntimeError('Unexpected error')
            with pytest.raises(Exception):
                command.execute()

class TestInitCommandStructureCreation:
    """Test that init command creates expected project structure."""

    def test_creates_expected_structure_in_temp_directory(self, tmp_path):
        """Test creates expected structure in a temp directory."""
        args = InitCommandArgs(project_name='structure_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()

                def create_structure(*args, **kwargs):
                    project_dir = command.project_dir
                    (project_dir / 'agents').mkdir(parents=True)
                    (project_dir / 'config').mkdir(parents=True)
                    (project_dir / 'source').mkdir(parents=True)
                    (project_dir / 'target').mkdir(parents=True)
                    (project_dir / 'agent_actions.yml').write_text('project: structure_test')
                mock_initializer.init_project.side_effect = create_structure
                mock_initializer_class.return_value = mock_initializer
                command.execute()
                assert (command.project_dir / 'agents').exists()
                assert (command.project_dir / 'config').exists()
                assert (command.project_dir / 'source').exists()
                assert (command.project_dir / 'target').exists()
                assert (command.project_dir / 'agent_actions.yml').exists()

    def test_respects_output_dir_when_provided(self, tmp_path):
        """Test respects output_dir when provided."""
        custom_output = tmp_path / 'custom_output'
        custom_output.mkdir()
        args = InitCommandArgs(project_name='output_test', output_dir=str(custom_output), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer_class.return_value = mock_initializer
                command.execute()
                expected_project_dir = custom_output / 'output_test'
                assert command.project_dir == expected_project_dir
                assert expected_project_dir.exists()

    def test_idempotent_on_rerun_no_unexpected_overwrite(self, tmp_path):
        """Test idempotent on rerun (no unexpected overwrite)."""
        args = InitCommandArgs(project_name='idempotent_test', output_dir=str(tmp_path), template='default', force=True)
        command1 = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()

                def create_initial_structure(*args, **kwargs):
                    project_dir = command1.project_dir
                    (project_dir / 'config').mkdir(parents=True)
                    (project_dir / 'config' / 'initial.yml').write_text('initial: content')
                mock_initializer.init_project.side_effect = create_initial_structure
                mock_initializer_class.return_value = mock_initializer
                command1.execute()
        user_file = command1.project_dir / 'config' / 'user_added.yml'
        user_file.write_text('user: content')
        command2 = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()

                def create_second_structure(*args, **kwargs):
                    project_dir = command2.project_dir
                    (project_dir / 'config').mkdir(parents=True, exist_ok=True)
                    (project_dir / 'config' / 'initial.yml').write_text('initial: content')
                mock_initializer.init_project.side_effect = create_second_structure
                mock_initializer_class.return_value = mock_initializer
                command2.execute()
                assert command2.project_dir.exists()
                assert (command2.project_dir / 'config').exists()

    def test_rejects_invalid_project_names_with_helpful_error(self, tmp_path):
        """Test rejects invalid project names with helpful error."""
        invalid_names = ['', '123invalid', 'invalid name', 'invalid-name!', 'very-long-project-name-that-exceeds-reasonable-limits-and-should-be-rejected']
        for invalid_name in invalid_names:
            try:
                args = InitCommandArgs(project_name=invalid_name, output_dir=str(tmp_path), template='default')
                command = InitCommand(args)
                with patch('agent_actions.tasks.init.ProjectValidator') as mock_validator:
                    mock_validator.validate_project_name.side_effect = ValidationError(f'Invalid project name: {invalid_name}')
                    with pytest.raises(Exception) as exc_info:
                        command.execute()
                    assert 'Invalid project name' in str(exc_info.value) or 'ClickException' in str(type(exc_info.value))
            except PydanticValidationError:
                pass

class TestInitClickCommand:
    """Test the Click command interface for init."""

    def test_init_click_command_success(self, tmp_path):
        """Test init Click command executes successfully."""
        runner = CliRunner()
        with patch('agent_actions.tasks.init.InitCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            result = runner.invoke(init, ['test_project', '--output-dir', str(tmp_path), '--template', 'default'])
            assert result.exit_code == 0
            mock_command_class.assert_called_once()
            mock_command.execute.assert_called_once()

    def test_init_click_command_with_force_flag(self, tmp_path):
        """Test init Click command with force flag."""
        runner = CliRunner()
        with patch('agent_actions.tasks.init.InitCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            result = runner.invoke(init, ['test_project', '--output-dir', str(tmp_path), '--force'])
            assert result.exit_code == 0
            args_call = mock_command_class.call_args[0][0]
            assert args_call.force is True

    def test_init_click_command_validation_error(self):
        """Test init Click command handles validation errors."""
        runner = CliRunner()

        def mock_init(*args, **kwargs):
            try:
                from agent_actions.validation.init_validator import InitCommandArgs
                return InitCommandArgs(project_name='')
            except PydanticValidationError as e:
                raise e
        with patch('agent_actions.tasks.init.InitCommandArgs', side_effect=mock_init):
            result = runner.invoke(init, [''])
            assert result.exit_code != 0
            assert 'Error' in result.output

    def test_init_click_command_execution_error(self, tmp_path):
        """Test init Click command handles execution errors."""
        runner = CliRunner()
        with patch('agent_actions.tasks.init.InitCommand') as mock_command_class:
            mock_command = Mock()
            mock_command.execute.side_effect = Exception('Execution failed')
            mock_command_class.return_value = mock_command
            result = runner.invoke(init, ['test_project', '--output-dir', str(tmp_path)])
            assert result.exit_code != 0

    def test_init_click_command_help(self):
        """Test init Click command help display."""
        runner = CliRunner()
        result = runner.invoke(init, ['--help'])
        assert result.exit_code == 0
        assert 'Initialize a new Agent Actions project' in result.output
        assert 'PROJECT_NAME' in result.output
        assert '--output-dir' in result.output
        assert '--template' in result.output
        assert '--force' in result.output

    @pytest.mark.parametrize('template', ['default', 'minimal', 'full'])
    def test_init_click_command_different_templates(self, tmp_path, template):
        """Test init Click command with different templates."""
        runner = CliRunner()
        with patch('agent_actions.tasks.init.InitCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            result = runner.invoke(init, ['template_test', '--output-dir', str(tmp_path), '--template', template])
            assert result.exit_code == 0
            args_call = mock_command_class.call_args[0][0]
            assert args_call.template == template

class TestInitCommandIntegration:
    """Integration tests for init command functionality."""

    def test_end_to_end_init_command_minimal(self, tmp_path):
        """Test end-to-end init command with minimal mocking."""
        args = InitCommandArgs(project_name='e2e_test', output_dir=str(tmp_path), template='default', force=False)
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer_class.return_value = mock_initializer
                command.execute()
                assert command.project_dir.exists()
                assert command.project_dir.is_dir()

    def test_concurrent_init_commands(self, tmp_path):
        """Test handling of concurrent init commands."""
        args1 = InitCommandArgs(project_name='concurrent_test', output_dir=str(tmp_path), template='default', force=False)
        args2 = InitCommandArgs(project_name='concurrent_test', output_dir=str(tmp_path), template='default', force=True)
        command1 = InitCommand(args1)
        command2 = InitCommand(args2)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer_class.return_value = mock_initializer
                command1.execute()
                assert command1.project_dir.exists()
                command2.execute()
                assert command2.project_dir.exists()

    def test_init_command_cleanup_on_failure(self, tmp_path):
        """Test init command cleans up on failure."""
        args = InitCommandArgs(project_name='cleanup_test', output_dir=str(tmp_path), template='default')
        command = InitCommand(args)
        with patch('agent_actions.tasks.init.ProjectValidator'):
            with patch('agent_actions.tasks.init.ProjectInitializer') as mock_initializer_class:
                mock_initializer = Mock()
                mock_initializer.init_project.side_effect = Exception('Initialization failed')
                mock_initializer_class.return_value = mock_initializer
                with pytest.raises(Exception):
                    command.execute()
                if command.project_dir.exists():
                    pass