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

    @pytest.mark.parametrize("command", ["run", "schema", "clean", "status"])
    def test_missing_agent_argument(self, runner, command):
        """The command exits as a usage error when --agent is missing."""
        result = runner.invoke(cli, [command])

        assert result.exit_code == 2
        assert "Missing option '-a' / '--agent'" in result.output
