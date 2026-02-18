"""Integration tests for CLI command registration and basic invocation."""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli


class TestCommandErrorHandling:
    """Test that commands handle missing arguments gracefully."""

    @pytest.fixture
    def runner(self):
        """Create a Click test runner."""
        return CliRunner()

    def test_run_missing_agent_argument(self, runner):
        """Test run command fails gracefully when --agent is missing."""
        result = runner.invoke(cli, ["run"])

        # Should fail but not crash
        assert result.exit_code != 0
        assert "agent" in result.output.lower() or "required" in result.output.lower()

    def test_schema_missing_agent_argument(self, runner):
        """Test schema command fails gracefully when --agent is missing."""
        result = runner.invoke(cli, ["schema"])

        # Should fail but not crash
        assert result.exit_code != 0
        assert "agent" in result.output.lower() or "required" in result.output.lower()

    def test_clean_missing_agent_argument(self, runner):
        """Test clean command fails gracefully when --agent is missing."""
        result = runner.invoke(cli, ["clean"])

        # Should fail but not crash
        assert result.exit_code != 0
        assert "agent" in result.output.lower() or "required" in result.output.lower()

    def test_status_missing_agent_argument(self, runner):
        """Test status command fails gracefully when --agent is missing."""
        result = runner.invoke(cli, ["status"])

        # Should fail but not crash
        assert result.exit_code != 0
        assert "agent" in result.output.lower() or "required" in result.output.lower()
