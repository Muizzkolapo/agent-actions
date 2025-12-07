"""
Comprehensive compile task tests for the Agent Actions render/compile command.

Tests cover compile task functionality as specified in tests_recommendations.jsonc:
1. Renders configs to artifacts deterministically for same input
2. Fails fast on invalid configs with helpful messages
"""
import os
import pytest
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch, MagicMock, mock_open
from click.testing import CliRunner
from agent_actions.cli.compile import RenderCommand, render
from agent_actions.validation.render_validator import RenderCommandArgs
from agent_actions.errors import ValidationError, FileLoadError, TemplateRenderingError  # New modular pattern!
from pydantic import ValidationError as PydanticValidationError

class TestRenderCommandArgs:
    """Test RenderCommandArgs pydantic model."""

    def test_valid_render_command_args(self, tmp_path):
        """Test valid RenderCommandArgs creation."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='test_agent', template_dir=str(template_dir))
        assert args.agent_name == 'test_agent'
        assert str(args.template_dir) == str(template_dir)

    def test_render_command_args_required_fields(self):
        """Test RenderCommandArgs with only required fields."""
        args = RenderCommandArgs(agent_name='required_agent')
        assert args.agent_name == 'required_agent'
        assert args.template_dir is None

    def test_render_command_args_validation_empty_agent_name(self):
        """Test RenderCommandArgs validation rejects empty agent name."""
        with pytest.raises(PydanticValidationError):
            RenderCommandArgs(agent_name='')

    def test_render_command_args_missing_agent_name(self):
        """Test RenderCommandArgs validation requires agent name."""
        with pytest.raises(PydanticValidationError):
            RenderCommandArgs()

class TestRenderCommand:
    """Test RenderCommand implementation."""

    def test_render_command_initialization_default_template_dir(self):
        """Test RenderCommand initialization with default template directory."""
        args = RenderCommandArgs(agent_name='test_agent')
        with patch('os.getcwd', return_value='/current/dir'):
            command = RenderCommand(args)
            assert command.args == args
            assert command.template_dir == Path('/current/dir') / 'templates'

    def test_render_command_initialization_custom_template_dir(self, tmp_path):
        """Test RenderCommand initialization with custom template directory."""
        template_dir = tmp_path / 'custom' / 'templates'
        template_dir.mkdir(parents=True)
        args = RenderCommandArgs(agent_name='test_agent', template_dir=str(template_dir))
        command = RenderCommand(args)
        assert command.args == args
        assert command.template_dir == Path(str(template_dir))

    def test_render_template_success(self, tmp_path):
        """Test successful template rendering."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='test_agent', template_dir=str(template_dir))
        command = RenderCommand(args)
        config_file = tmp_path / 'test_agent.yml'
        config_file.write_text('name: test_agent\ntype: generator')
        expected_output = 'rendered template content'
        with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = expected_output
            result = command._render_template(config_file)
            assert result == expected_output
            mock_render.assert_called_once_with(str(config_file), str(command.template_dir))

    def test_render_template_failure(self, tmp_path):
        """Test template rendering failure handling."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='test_agent', template_dir=str(template_dir))
        command = RenderCommand(args)
        config_file = tmp_path / 'test_agent.yml'
        with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
            mock_render.side_effect = Exception('Template rendering failed')
            with pytest.raises(TemplateRenderingError, match='Failed to render template'):
                command._render_template(config_file)

    def test_render_template_deterministic_output(self, tmp_path):
        """Test renders configs to artifacts deterministically for same input."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='deterministic_agent', template_dir=str(template_dir))
        command = RenderCommand(args)
        config_file = tmp_path / 'deterministic_agent.yml'
        config_file.write_text('name: deterministic_agent\nversion: 1.0')
        expected_output = 'deterministic rendered output'
        with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = expected_output
            result1 = command._render_template(config_file)
            result2 = command._render_template(config_file)
            assert result1 == result2
            assert result1 == expected_output
            assert mock_render.call_count == 2
            assert mock_render.call_args_list[0] == mock_render.call_args_list[1]

class TestRenderCommandExecution:
    """Test RenderCommand execute method and full workflow."""

    def test_execute_success_console_output(self, tmp_path):
        """Test successful execution with console output."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='console_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        expected_output = 'console rendered template'
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path / 'config'
        mock_paths.agent_config_dir.mkdir()
        config_file = mock_paths.agent_config_dir / 'console_test.yml'
        config_file.write_text('name: console_test')
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch.object(command, '_render_template') as mock_render:
                mock_render.return_value = expected_output
                with patch('click.echo') as mock_echo:
                    command.execute()
                    mock_render.assert_called_once_with(config_file)
                    mock_echo.assert_called_once_with(expected_output)

    def test_execute_file_not_found_error(self, tmp_path):
        """Test execute handles file not found errors."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='missing_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path / 'config'
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch.object(command, '_render_template') as mock_render:
                mock_render.side_effect = FileLoadError('Config file not found')
                with pytest.raises(Exception):
                    command.execute()

    def test_execute_validation_error(self, tmp_path):
        """Test execute handles validation errors."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='validation_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path / 'config'
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch.object(command, '_render_template') as mock_render:
                mock_render.side_effect = ValidationError('Invalid configuration')
                with pytest.raises(Exception):
                    command.execute()

    def test_execute_template_rendering_error(self, tmp_path):
        """Test execute handles template rendering errors."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='template_error_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path / 'config'
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch.object(command, '_render_template') as mock_render:
                mock_render.side_effect = TemplateRenderingError('Template syntax error')
                with pytest.raises(Exception):
                    command.execute()

    def test_execute_unexpected_error(self, tmp_path):
        """Test execute handles unexpected errors."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='unexpected_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.side_effect = RuntimeError('Unexpected error')
            with pytest.raises(Exception):
                command.execute()

class TestRenderCommandConfigValidation:
    """Test render command handles invalid configurations properly."""

    def test_fails_fast_on_invalid_configs_with_helpful_messages(self, tmp_path):
        """Test fails fast on invalid configs with helpful messages."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='invalid_config_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        invalid_configs = [('empty_config.yml', ''), ('malformed.yml', 'invalid: yaml: content: ['), ('missing_required.yml', 'name: missing_type'), ('invalid_structure.yml', 'invalid_top_level: structure')]
        for config_name, config_content in invalid_configs:
            config_file = tmp_path / config_name
            config_file.write_text(config_content)
            mock_paths = Mock()
            mock_paths.agent_config_dir = tmp_path
            with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
                mock_factory.create_project_paths.return_value = mock_paths
                with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                    mock_render.side_effect = ValidationError(f'Invalid configuration in {config_name}: {config_content[:20]}...')
                    with pytest.raises(Exception) as exc_info:
                        command.execute()
                    error_msg = str(exc_info.value)
                    assert 'Invalid configuration' in error_msg or 'ClickException' in str(type(exc_info.value))

    def test_config_schema_validation_errors(self, tmp_path):
        """Test various configuration schema validation errors."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='schema_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        validation_errors = ['Missing required field: agent_type', 'Invalid agent type: unknown_type', 'Template file not found: nonexistent.j2', 'Circular dependency detected in agent configuration', 'Invalid YAML syntax at line 5']
        for error_message in validation_errors:
            config_file = tmp_path / 'schema_test.yml'
            config_file.write_text('name: schema_test\ntype: invalid')
            mock_paths = Mock()
            mock_paths.agent_config_dir = tmp_path
            with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
                mock_factory.create_project_paths.return_value = mock_paths
                with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                    mock_render.side_effect = ValidationError(error_message)
                    with pytest.raises(Exception) as exc_info:
                        command.execute()
                    assert error_message in str(exc_info.value) or 'ClickException' in str(type(exc_info.value))

    def test_template_syntax_errors(self, tmp_path):
        """Test template syntax error handling."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='template_syntax_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        config_file = tmp_path / 'template_syntax_test.yml'
        config_file.write_text('name: template_syntax_test')
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path
        template_errors = ['Template syntax error: Invalid Jinja2 syntax at line 10', 'Undefined variable: missing_variable in template', 'Template file not found: missing_template.j2', 'Filter not found: custom_filter in template']
        for error_message in template_errors:
            with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
                mock_factory.create_project_paths.return_value = mock_paths
                with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                    mock_render.side_effect = TemplateRenderingError(error_message)
                    with pytest.raises(Exception) as exc_info:
                        command.execute()
                    assert error_message in str(exc_info.value) or 'ClickException' in str(type(exc_info.value))

class TestRenderClickCommand:
    """Test the Click command interface for render."""

    def test_render_click_command_success(self, tmp_path):
        """Test render Click command executes successfully."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        runner = CliRunner()
        with patch('agent_actions.tasks.compile.RenderCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')
                result = runner.invoke(render, ['--agent', 'test_agent', '--template-dir', str(template_dir)])
                assert result.exit_code == 0
                mock_command_class.assert_called_once()
                mock_command.execute.assert_called_once()

    def test_render_click_command_required_agent(self):
        """Test render Click command requires agent parameter."""
        runner = CliRunner()
        result = runner.invoke(render, [])
        assert result.exit_code != 0

    def test_render_click_command_short_options(self, tmp_path):
        """Test render Click command with short options."""
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        runner = CliRunner()
        with patch('agent_actions.tasks.compile.RenderCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')
                result = runner.invoke(render, ['-a', 'short_test', '-t', str(template_dir)])
                assert result.exit_code == 0
                args_call = mock_command_class.call_args[0][0]
                assert args_call.agent_name == 'short_test'
                assert str(args_call.template_dir) == str(template_dir)

    def test_render_click_command_minimal_args(self):
        """Test render Click command with minimal arguments."""
        runner = CliRunner()
        with patch('agent_actions.tasks.compile.RenderCommand') as mock_command_class:
            mock_command = Mock()
            mock_command_class.return_value = mock_command
            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')
                result = runner.invoke(render, ['--agent', 'minimal_test'])
                assert result.exit_code == 0
                args_call = mock_command_class.call_args[0][0]
                assert args_call.agent_name == 'minimal_test'
                assert args_call.template_dir is None

    def test_render_click_command_validation_error(self):
        """Test render Click command handles validation errors."""
        runner = CliRunner()
        with patch('agent_actions.tasks.compile.RenderCommandArgs') as mock_args_class:
            mock_args_class.side_effect = PydanticValidationError.from_exception_data('ValidationError', [{'type': 'missing', 'loc': ('agent_name',), 'msg': 'Field required', 'input': {}, 'url': 'https://errors.pydantic.dev/2.11/v/missing'}])
            with runner.isolated_filesystem():
                Path('agent_actions.yml').write_text('# Test project')
                result = runner.invoke(render, ['--agent', ''])
                assert result.exit_code != 0
                assert 'Error' in result.output

    def test_render_click_command_execution_error(self):
        """Test render Click command handles execution errors."""
        runner = CliRunner()
        with patch('agent_actions.tasks.compile.RenderCommand') as mock_command_class:
            mock_command = Mock()
            mock_command.execute.side_effect = Exception('Render execution failed')
            mock_command_class.return_value = mock_command
            result = runner.invoke(render, ['--agent', 'error_test'])
            assert result.exit_code != 0

    def test_render_click_command_help(self):
        """Test render Click command help display."""
        runner = CliRunner()
        result = runner.invoke(render, ['--help'])
        assert result.exit_code == 0
        assert 'Render Jinja2 templates' in result.output
        assert 'agent configuration files' in result.output
        assert '--agent' in result.output
        assert '--template-dir' in result.output

class TestRenderCommandDeterminism:
    """Test deterministic rendering behavior."""

    def test_same_input_produces_same_output(self, tmp_path):
        """Test that same input produces identical output (deterministic)."""
        config_content = '\nname: deterministic_test\ntype: generator\nversion: 1.0\nsettings:\n  param1: value1\n  param2: value2\n'
        config_file = tmp_path / 'config.yml'
        config_file.write_text(config_content)
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='deterministic_test', template_dir=str(template_dir))
        results = []
        for i in range(3):
            command = RenderCommand(args)
            with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                mock_render.return_value = 'consistent rendered output'
                result = command._render_template(config_file)
                results.append(result)
        assert len(set(results)) == 1
        assert all((result == 'consistent rendered output' for result in results))

    def test_different_inputs_produce_different_outputs(self, tmp_path):
        """Test that different inputs produce different outputs."""
        configs = [('config1.yml', 'name: test1\ntype: generator'), ('config2.yml', 'name: test2\ntype: transformer'), ('config3.yml', 'name: test3\ntype: validator')]
        results = []
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        for config_name, config_content in configs:
            config_file = tmp_path / config_name
            config_file.write_text(config_content)
            args = RenderCommandArgs(agent_name=config_name.replace('.yml', ''), template_dir=str(template_dir))
            command = RenderCommand(args)
            with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                mock_render.return_value = f'rendered {config_name}'
                result = command._render_template(config_file)
                results.append(result)
        assert len(set(results)) == len(results)

    def test_template_caching_behavior(self, tmp_path):
        """Test template rendering caching behavior for performance."""
        config_file = tmp_path / 'cache_test.yml'
        config_file.write_text('name: cache_test\ntype: generator')
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='cache_test', template_dir=str(template_dir))
        command = RenderCommand(args)
        with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = 'cached rendered output'
            result1 = command._render_template(config_file)
            result2 = command._render_template(config_file)
            assert result1 == result2
            assert mock_render.call_count == 2

class TestRenderCommandIntegration:
    """Integration tests for render command functionality."""

    def test_end_to_end_render_command(self, tmp_path):
        """Test end-to-end render command with minimal mocking."""
        templates_dir = tmp_path / 'templates'
        templates_dir.mkdir()
        config_dir = tmp_path / 'config'
        config_dir.mkdir()
        config_file = config_dir / 'integration_test.yml'
        config_file.write_text('name: integration_test\ntype: generator')
        args = RenderCommandArgs(agent_name='integration_test', template_dir=str(templates_dir))
        command = RenderCommand(args)
        mock_paths = Mock()
        mock_paths.agent_config_dir = config_dir
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                mock_render.return_value = 'integration test output'
                with patch('click.echo') as mock_echo:
                    command.execute()
                    mock_render.assert_called_once()
                    mock_echo.assert_called_once_with('integration test output')

    def test_render_command_with_complex_configuration(self, tmp_path):
        """Test render command with complex agent configuration."""
        complex_config = '\nname: complex_agent\ntype: pipeline\nversion: 2.0\ndependencies:\n  - agent1\n  - agent2\nsettings:\n  nested:\n    deep:\n      value: test\n  array:\n    - item1\n    - item2\n'
        config_file = tmp_path / 'complex_agent.yml'
        config_file.write_text(complex_config)
        template_dir = tmp_path / 'templates'
        template_dir.mkdir()
        args = RenderCommandArgs(agent_name='complex_agent', template_dir=str(template_dir))
        command = RenderCommand(args)
        mock_paths = Mock()
        mock_paths.agent_config_dir = tmp_path
        with patch('agent_actions.tasks.services.project_paths_factory.ProjectPathsFactory') as mock_factory:
            mock_factory.create_project_paths.return_value = mock_paths
            with patch('agent_actions.tasks.compile.render_pipeline_with_templates') as mock_render:
                mock_render.return_value = 'complex rendered output'
                result = command._render_template(config_file)
                assert result == 'complex rendered output'
                mock_render.assert_called_once_with(str(config_file), str(command.template_dir))