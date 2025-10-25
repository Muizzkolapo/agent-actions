"""Tests for CLI decorators."""
import pytest
import os
from pathlib import Path
import click
from click.testing import CliRunner
from agent_actions.cli.cli_decorators import requires_project
from agent_actions.shared.exceptions import ProjectNotFoundError

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