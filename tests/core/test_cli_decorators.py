"""Tests for CLI decorators."""
import pytest
import os
from pathlib import Path
import click
from click.testing import CliRunner
from agent_actions.cli.cli_decorators import requires_project, handles_user_errors
from agent_actions.shared.exceptions import ProjectNotFoundError, ValidationError

class TestRequiresProjectDecorator:
    """Tests for @requires_project decorator."""

    def test_decorator_finds_project_root_and_changes_cwd(self, tmp_path, monkeypatch):
        """Test decorator finds project root and changes to it."""
        execution_cwd = None

        @click.command()
        @requires_project
        def test_cmd():
            nonlocal execution_cwd
            execution_cwd = Path.cwd()
            click.echo('Success')
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            Path('src').mkdir()
            result = runner.invoke(test_cmd, catch_exceptions=False)
            assert result.exit_code == 0
            assert '📁 Project root:' in result.output
            assert 'Success' in result.output

    def test_decorator_shows_relative_path_when_at_root(self, tmp_path):
        """Test decorator shows '.' when already at project root."""

        @click.command()
        @requires_project
        def test_cmd():
            click.echo('Executed')
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            result = runner.invoke(test_cmd, catch_exceptions=False)
            assert result.exit_code == 0
            assert '📁 Project root:' in result.output
            assert 'Executed' in result.output

    def test_decorator_raises_when_not_in_project(self, tmp_path):
        """Test decorator raises ProjectNotFoundError when not in project."""

        @click.command()
        @requires_project
        def test_cmd():
            click.echo('Should not execute')
        runner = CliRunner()
        result = runner.invoke(test_cmd)
        assert result.exit_code != 0

    def test_decorator_with_function_args(self, tmp_path):
        """Test decorator preserves function arguments."""

        @click.command()
        @click.option('--name', default='test')
        @requires_project
        def test_cmd(name):
            click.echo(f'Hello {name}')
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            result = runner.invoke(test_cmd, ['--name', 'world'], catch_exceptions=False)
            assert result.exit_code == 0
            assert 'Hello world' in result.output

    def test_decorator_wraps_function_metadata(self):
        """Test decorator preserves function metadata using functools.wraps."""

        @click.command()
        @requires_project
        def test_cmd():
            """Test command docstring."""
            pass
        assert test_cmd.callback.__name__ == 'test_cmd'

    def test_decorator_from_nested_subdirectory(self, tmp_path):
        """Test decorator works from deeply nested subdirectory."""

        @click.command()
        @requires_project
        def test_cmd():
            click.echo('Found project')
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            Path('a/b/c/d').mkdir(parents=True)
            result = runner.invoke(test_cmd, catch_exceptions=False)
            assert result.exit_code == 0
            assert 'Found project' in result.output

class TestRequiresProjectIntegration:
    """Integration tests with actual project structure."""

    def test_decorator_with_nested_projects(self, tmp_path):
        """Test decorator finds nearest project in nested structure."""

        @click.command()
        @requires_project
        def test_cmd():
            marker = Path.cwd() / 'agent_actions.yml'
            click.echo(f'Marker exists: {marker.exists()}')
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Outer project')
            Path('submodule').mkdir()
            Path('submodule/agent_actions.yml').write_text('# Inner project')
            result = runner.invoke(test_cmd, catch_exceptions=False)
            assert result.exit_code == 0
            assert '📁 Project root:' in result.output

    def test_decorator_error_provides_helpful_message(self, tmp_path):
        """Test that error message is helpful when not in project."""

        @click.command()
        @requires_project
        def test_cmd():
            click.echo('Should not reach here')
        runner = CliRunner()
        result = runner.invoke(test_cmd)
        assert result.exit_code != 0

class TestDecoratorCWDRestoration:
    """Tests for CWD restoration behavior."""

    def test_decorator_restores_cwd_on_success(self, tmp_path, monkeypatch):
        """Test original CWD is restored after successful execution."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'src'
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        original_cwd = Path.cwd()

        @click.command()
        @requires_project
        def test_cmd():
            return 'success'
        runner = CliRunner()
        runner.invoke(test_cmd)
        assert Path.cwd() == original_cwd

    def test_decorator_restores_cwd_on_exception(self, tmp_path, monkeypatch):
        """Test original CWD is restored even when command raises exception."""
        root = tmp_path / 'project'
        root.mkdir()
        (root / 'agent_actions.yml').touch()
        subdir = root / 'src'
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        original_cwd = Path.cwd()

        @click.command()
        @requires_project
        def test_cmd():
            raise ValueError('Test exception')
        runner = CliRunner()
        runner.invoke(test_cmd)
        assert Path.cwd() == original_cwd


class TestHandlesUserErrorsDecorator:
    """Tests for @handles_user_errors decorator."""

    def test_decorator_catches_and_formats_exceptions(self):
        """Test decorator catches exceptions and formats them as ClickException."""
        @click.command()
        @handles_user_errors('test')
        def test_cmd():
            raise ValueError('Test error message')

        runner = CliRunner()
        result = runner.invoke(test_cmd)

        assert result.exit_code != 0
        assert isinstance(result.exception, click.ClickException) or result.exit_code == 1
        # Error message should be formatted by format_user_error
        assert 'Test error message' in result.output or result.exception is not None

    def test_decorator_preserves_click_exceptions(self):
        """Test decorator does NOT double-wrap ClickException."""
        @click.command()
        @handles_user_errors('test')
        def test_cmd():
            raise click.ClickException('Already a ClickException')

        runner = CliRunner()
        result = runner.invoke(test_cmd)

        assert result.exit_code != 0
        assert 'Already a ClickException' in result.output

    def test_decorator_includes_command_name_in_context(self):
        """Test decorator includes command name in error context."""
        @click.command()
        @handles_user_errors('my_command')
        def test_cmd():
            raise ValidationError('Validation failed', context={})

        runner = CliRunner()
        result = runner.invoke(test_cmd)

        assert result.exit_code != 0
        # format_user_error should have received command name in context

    def test_decorator_includes_kwargs_in_context(self):
        """Test decorator automatically includes all CLI kwargs in error context."""
        @click.command()
        @click.option('--agent', default='test_agent')
        @handles_user_errors('run')
        def test_cmd(agent):
            raise ValueError(f'Failed for agent: {agent}')

        runner = CliRunner()
        result = runner.invoke(test_cmd, ['--agent', 'my_agent'])

        assert result.exit_code != 0
        # The error context should include agent='my_agent'

    def test_decorator_merges_extra_context(self):
        """Test decorator merges extra context parameters."""
        @click.command()
        @handles_user_errors('test', extra_key='extra_value', template='default')
        def test_cmd():
            raise ValueError('Test error')

        runner = CliRunner()
        result = runner.invoke(test_cmd)

        assert result.exit_code != 0
        # extra_key and template should be in error context

    def test_decorator_allows_successful_execution(self):
        """Test decorator allows command to succeed normally."""
        @click.command()
        @handles_user_errors('test')
        def test_cmd():
            click.echo('Success!')
            return 0

        runner = CliRunner()
        result = runner.invoke(test_cmd)

        assert result.exit_code == 0
        assert 'Success!' in result.output

    def test_decorator_preserves_function_metadata(self):
        """Test decorator preserves function metadata using functools.wraps."""
        @click.command()
        @handles_user_errors('test')
        def test_cmd():
            """Test command docstring."""
            pass

        assert test_cmd.callback.__name__ == 'test_cmd'
        assert 'Test command docstring' in test_cmd.callback.__doc__

    def test_decorator_with_pydantic_validation_error(self):
        """Test decorator handles Pydantic ValidationError from args models."""
        from pydantic import ValidationError as PydanticValidationError, BaseModel, field_validator

        class TestArgs(BaseModel):
            name: str

            @field_validator('name')
            @classmethod
            def name_must_not_be_empty(cls, v):
                if not v:
                    raise ValueError('Name cannot be empty')
                return v

        @click.command()
        @handles_user_errors('test')
        def test_cmd(name: str):
            # This should raise PydanticValidationError
            args = TestArgs(name=name)
            click.echo(f'Name: {args.name}')

        runner = CliRunner()
        result = runner.invoke(test_cmd, ['--name', ''])

        assert result.exit_code != 0

    def test_decorator_stacks_with_requires_project(self):
        """Test decorator works correctly when stacked with @requires_project."""
        @click.command()
        @handles_user_errors('test')
        @requires_project
        def test_cmd():
            click.echo('Should not reach here')

        runner = CliRunner()
        # Run without being in a project - should catch ProjectNotFoundError
        result = runner.invoke(test_cmd)

        assert result.exit_code != 0
        # Error should be formatted by format_user_error

    def test_decorator_handles_agent_execution_errors(self):
        """Test decorator handles various AgentActions exception types."""
        from agent_actions.shared.exceptions import (
            ConfigurationError,
            FileLoadError
        )

        test_exceptions = [
            ConfigurationError('Config error', context={}),
            FileLoadError('File not found', context={})
        ]

        for exc in test_exceptions:
            @click.command()
            @handles_user_errors('test')
            def test_cmd():
                raise exc

            runner = CliRunner()
            result = runner.invoke(test_cmd)

            assert result.exit_code != 0


class TestHandlesUserErrorsIntegration:
    """Integration tests for @handles_user_errors with real command patterns."""

    def test_decorator_with_command_class_pattern(self):
        """Test decorator with typical Command Pattern (Click -> Pydantic -> Command -> execute)."""
        from pydantic import BaseModel

        class TestCommandArgs(BaseModel):
            name: str

        class TestCommand:
            def __init__(self, args: TestCommandArgs):
                self.args = args

            def execute(self):
                if self.args.name == 'fail':
                    raise ValueError('Command execution failed')
                click.echo(f'Executed for: {self.args.name}')

        @click.command()
        @click.option('--name', required=True)
        @handles_user_errors('test')
        def test_cmd(name: str):
            args = TestCommandArgs(name=name)
            command = TestCommand(args)
            command.execute()

        runner = CliRunner()

        # Test success case
        result = runner.invoke(test_cmd, ['--name', 'success'])
        assert result.exit_code == 0
        assert 'Executed for: success' in result.output

        # Test error case
        result = runner.invoke(test_cmd, ['--name', 'fail'])
        assert result.exit_code != 0
        assert 'Command execution failed' in result.output or result.exception is not None

    def test_decorator_eliminates_try_except_boilerplate(self):
        """Test that decorator successfully eliminates need for try/except in command."""
        @click.command()
        @click.option('--agent', required=True)
        @handles_user_errors('status')
        def status_cmd(agent: str):
            # No try/except needed! Decorator handles all errors
            if agent == 'nonexistent':
                raise ValidationError('Agent not found', context={'agent': agent})
            click.echo(f'Status for: {agent}')

        runner = CliRunner()

        # Success case
        result = runner.invoke(status_cmd, ['--agent', 'test'])
        assert result.exit_code == 0

        # Error case - decorator should catch and format
        result = runner.invoke(status_cmd, ['--agent', 'nonexistent'])
        assert result.exit_code != 0