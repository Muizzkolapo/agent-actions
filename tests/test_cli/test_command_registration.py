"""Integration tests for CLI command registration and basic invocation."""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli


class TestCommandRegistration:
    """Test that all CLI commands are properly registered and invokable."""

    @pytest.fixture
    def runner(self):
        """Create a Click test runner."""
        return CliRunner()

    def test_all_commands_registered(self, runner):
        """Verify all 14 expected commands are registered in the CLI."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0, f"CLI --help failed: {result.output}"

        # All expected commands should be listed
        expected_commands = [
            "batch",
            "clean",
            "compile",
            "docs",
            "init",
            "inspect",
            "list-udfs",
            "preview",
            "render",
            "run",
            "schema",
            "skills",
            "status",
            "validate-udfs",
        ]

        for command in expected_commands:
            assert command in result.output, f"Command '{command}' not found in CLI help"

    def test_clean_command_help(self, runner):
        """Test clean command (formerly test.py) is properly registered."""
        result = runner.invoke(cli, ["clean", "--help"])

        assert result.exit_code == 0
        assert "Remove temporary directories" in result.output
        assert "--agent" in result.output
        assert "--force" in result.output
        assert "--all" in result.output

    def test_run_command_help(self, runner):
        """Test run command shows help correctly."""
        result = runner.invoke(cli, ["run", "--help"])

        assert result.exit_code == 0
        assert "--agent" in result.output
        assert "--validate-only" in result.output or "-v" in result.output

    def test_schema_command_help(self, runner):
        """Test schema command shows help correctly."""
        result = runner.invoke(cli, ["schema", "--help"])

        assert result.exit_code == 0
        assert "--agent" in result.output

    def test_inspect_command_help(self, runner):
        """Test inspect command shows subcommands."""
        result = runner.invoke(cli, ["inspect", "--help"])

        assert result.exit_code == 0
        assert "dependencies" in result.output or "graph" in result.output

    def test_init_command_help(self, runner):
        """Test init command shows help correctly."""
        result = runner.invoke(cli, ["init", "--help"])

        assert result.exit_code == 0
        assert "Initialize" in result.output or "project" in result.output

    def test_preview_command_help(self, runner):
        """Test preview command (unique to commands/) is accessible."""
        result = runner.invoke(cli, ["preview", "--help"])

        assert result.exit_code == 0
        assert "preview" in result.output.lower()

    def test_status_command_help(self, runner):
        """Test status command shows help correctly."""
        result = runner.invoke(cli, ["status", "--help"])

        assert result.exit_code == 0
        assert "--agent" in result.output

    def test_list_udfs_command_help(self, runner):
        """Test list-udfs command shows help correctly."""
        result = runner.invoke(cli, ["list-udfs", "--help"])

        assert result.exit_code == 0
        assert "UDF" in result.output or "function" in result.output.lower()

    def test_docs_command_help(self, runner):
        """Test docs command shows subcommands."""
        result = runner.invoke(cli, ["docs", "--help"])

        assert result.exit_code == 0

    def test_skills_command_help(self, runner):
        """Test skills command shows subcommands."""
        result = runner.invoke(cli, ["skills", "--help"])

        assert result.exit_code == 0

    def test_compile_command_help(self, runner):
        """Test compile command (alias for render) shows help."""
        result = runner.invoke(cli, ["compile", "--help"])

        assert result.exit_code == 0

    def test_render_command_help(self, runner):
        """Test render command shows help correctly."""
        result = runner.invoke(cli, ["render", "--help"])

        assert result.exit_code == 0


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


class TestGlobalOptions:
    """Test global CLI options work across commands."""

    @pytest.fixture
    def runner(self):
        """Create a Click test runner."""
        return CliRunner()

    def test_version_flag(self, runner):
        """Test --version flag shows version."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        # Should show some version info
        assert len(result.output.strip()) > 0

    def test_help_flag(self, runner):
        """Test --help flag shows help."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "Agent Actions CLI" in result.output or "COMMAND" in result.output

    def test_verbose_flag_accepted(self, runner):
        """Test -v/--verbose flag is accepted (even if command fails)."""
        # Use with a command that will fail but should accept the flag
        result = runner.invoke(cli, ["-v", "run"])

        # May fail for other reasons (missing agent), but shouldn't fail on -v flag parse
        # The important thing is it doesn't say "no such option: -v"
        assert "no such option: -v" not in result.output.lower()

    def test_debug_flag_accepted(self, runner):
        """Test --debug flag is accepted."""
        result = runner.invoke(cli, ["--debug", "run"])

        # May fail for other reasons, but shouldn't fail on --debug flag parse
        assert "no such option: --debug" not in result.output.lower()

    def test_quiet_flag_accepted(self, runner):
        """Test -q/--quiet flag is accepted."""
        result = runner.invoke(cli, ["-q", "run"])

        # May fail for other reasons, but shouldn't fail on -q flag parse
        assert "no such option: -q" not in result.output.lower()
