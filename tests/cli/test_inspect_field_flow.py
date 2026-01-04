"""CLI integration tests for the inspect field-flow command.

Note: Tests that require full project setup are marked with pytest.mark.skip
because the project structure is complex. The core FieldFlowAnalyzer logic
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


class TestInspectFieldFlowCommand:
    """Tests for the inspect field-flow CLI command."""

    def test_help_message(self, cli_runner):
        """Test that help message is displayed correctly."""
        result = cli_runner.invoke(cli, ["inspect", "field-flow", "--help"])

        assert result.exit_code == 0
        assert "Trace and visualize data flow" in result.output
        assert "--agent" in result.output
        assert "--json" in result.output
        assert "--verbose" in result.output
        assert "--errors-only" in result.output
        assert "--field" in result.output

    def test_inspect_group_help(self, cli_runner):
        """Test that inspect group help is displayed."""
        result = cli_runner.invoke(cli, ["inspect", "--help"])

        assert result.exit_code == 0
        assert "field-flow" in result.output
        assert "Inspect workflow structure" in result.output

    def test_field_flow_requires_agent_option(self, cli_runner):
        """Test that --agent option is required."""
        result = cli_runner.invoke(cli, ["inspect", "field-flow"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_field_flow_requires_project(self, cli_runner, tmp_path):
        """Test command fails gracefully outside project."""
        os.chdir(tmp_path)  # No agent_actions.yml here

        result = cli_runner.invoke(cli, ["inspect", "field-flow", "-a", "test_workflow"])

        # Should fail because not in a project
        assert result.exit_code != 0

    def test_field_flow_invalid_agent_in_project(self, cli_runner, tmp_path):
        """Test error handling for non-existent agent within a project."""
        # Create minimal project marker
        (tmp_path / "agent_actions.yml").write_text("name: test_project\nversion: 1.0.0\n")
        os.chdir(tmp_path)

        result = cli_runner.invoke(cli, ["inspect", "field-flow", "-a", "nonexistent_workflow"])

        # Should fail gracefully with helpful error
        assert result.exit_code != 0
        assert "not found" in result.output.lower() or "error" in result.output.lower()


class TestInspectCommandGroup:
    """Tests for the inspect command group structure."""

    def test_inspect_is_a_group(self, cli_runner):
        """Test that inspect is a command group."""
        result = cli_runner.invoke(cli, ["inspect"])

        # Should show usage/help for the group
        assert result.exit_code == 0 or "Usage:" in result.output

    def test_inspect_field_flow_is_subcommand(self, cli_runner):
        """Test that field-flow is a subcommand of inspect."""
        result = cli_runner.invoke(cli, ["inspect", "--help"])

        assert "field-flow" in result.output
        assert result.exit_code == 0
