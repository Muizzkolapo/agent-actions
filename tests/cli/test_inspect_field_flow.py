"""CLI integration tests for the inspect commands.

Note: Tests that require full project setup are marked with pytest.mark.skip
because the project structure is complex. The core analysis logic
is tested in tests/validation/static_analyzer/test_field_flow_analyzer.py
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli


@pytest.fixture
def cli_runner():
    """Provide a Click CliRunner for testing CLI commands."""
    return CliRunner()


class TestInspectDependenciesCommand:
    """Tests for the inspect dependencies CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "dependencies", "--help"])

        assert result.exit_code == 0
        assert "Analyze workflow dependencies" in result.output
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_dependencies_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "dependencies"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestInspectGraphCommand:
    """Tests for the inspect graph CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "graph", "--help"])

        assert result.exit_code == 0
        assert "dependency graph" in result.output.lower()
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_graph_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "graph"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestInspectActionCommand:
    """Tests for the inspect action CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "action", "--help"])

        assert result.exit_code == 0
        assert "details for a specific action" in result.output.lower()
        assert "--agent" in result.output
        assert "--json" in result.output

    def test_action_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "action", "test_action"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_action_requires_action_name(self, cli_runner):
        """Test that action name argument is required."""
        result = cli_runner.invoke(cli, ["inspect", "action", "-a", "test_workflow"])

        assert result.exit_code != 0
        assert "Missing argument" in result.output or "required" in result.output.lower()


class TestInspectCommandGroup:
    """Tests for the inspect command group structure."""

    def test_inspect_is_a_group(self, cli_runner):
        """Test that inspect is a command group."""
        result = cli_runner.invoke(cli, ["inspect"])

        # Should show usage/help for the group
        assert result.exit_code == 0 or "Usage:" in result.output

    def test_inspect_group_help(self, cli_runner):
        """Test that inspect group help is displayed."""
        result = cli_runner.invoke(cli, ["inspect", "--help"])

        assert result.exit_code == 0
        assert "dependencies" in result.output
        assert "graph" in result.output
        assert "action" in result.output
        assert "Inspect workflow structure" in result.output

    def test_inspect_subcommands_available(self, cli_runner):
        """Test that all subcommands are listed."""
        result = cli_runner.invoke(cli, ["inspect", "--help"])

        assert "dependencies" in result.output
        assert "graph" in result.output
        assert "action" in result.output
        assert result.exit_code == 0
