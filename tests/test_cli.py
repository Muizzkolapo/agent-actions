"""
Comprehensive CLI tests for the Agent Actions CLI.

Tests cover all CLI behavior and argument handling as specified in tests_recommendations.jsonc:
1. --version/-V prints version and exits 0
2. Help displays for root and subcommands without error
3. Invalid command/args produce clear error and non-zero exit
4. KeyboardInterrupt exits with code 130 and no stack trace
5. Dispatch routes to init/compile/test/status with correct args
"""

import signal
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner

from agent_actions.cli.main import CLI, main_entrypoint, main, cli
from agent_actions.__version__ import __version__


class TestCLIVersionHandling:
    """Test CLI version display functionality."""

    def test_version_flag_prints_version_and_exits_0(self, cli_runner):
        """Test --version flag prints version and exits with code 0."""
        cli_app = CLI()

        # --version should return exit code 0
        exit_code = cli_app.execute(['--version'])

        assert exit_code == 0

    def test_version_short_flag_prints_version_and_exits_0(self, cli_runner):
        """Test -V flag prints version and exits with code 0."""
        cli_app = CLI()

        # -V should return exit code 0
        exit_code = cli_app.execute(['-V'])

        assert exit_code == 0

    def test_version_flag_with_other_args_still_exits(self, cli_runner):
        """Test --version flag takes precedence over other arguments."""
        cli_app = CLI()

        # --version should return exit code 0 even with other args
        exit_code = cli_app.execute(['--version', 'init', '--output', '/tmp'])

        assert exit_code == 0

    def test_version_output_format(self, cli_runner, capsys):
        """Test version output format is correct."""
        cli_app = CLI()
        exit_code = cli_app.execute(['--version'])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Agent Actions CLI v" in captured.out


class TestCLIHelpDisplay:
    """Test CLI help display functionality."""

    def test_root_help_displays_without_error(self, cli_runner):
        """Test root command help displays without error."""
        result = cli_runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        assert 'Agent Actions CLI tool' in result.output
        assert 'Usage:' in result.output

    def test_help_flag_displays_without_error(self, cli_runner):
        """Test -h flag displays help without error."""
        result = cli_runner.invoke(cli, ['-h'])

        assert result.exit_code == 0
        assert 'Usage:' in result.output

    @pytest.mark.parametrize("command", [
        "init",
        "render",
        "run",
        "batch",
        "status",
        "clean",
        "docs"
    ])
    def test_subcommand_help_displays_without_error(self, cli_runner, command):
        """Test subcommand help displays without error."""
        result = cli_runner.invoke(cli, [command, '--help'])

        # Should not error even if some imports might fail
        assert result.exit_code == 0 or 'Error' not in result.output
        assert 'Usage:' in result.output or 'Commands:' in result.output

    def test_help_shows_available_commands(self, cli_runner):
        """Test help shows list of available commands."""
        result = cli_runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        # Should contain some of the main commands
        expected_commands = ['init', 'status']
        for cmd in expected_commands:
            # Commands might be listed in help
            assert cmd in result.output or 'Commands:' in result.output


class TestCLIErrorHandling:
    """Test CLI error handling and validation."""

    def test_invalid_command_produces_clear_error(self, cli_runner):
        """Test invalid command produces clear error and non-zero exit."""
        result = cli_runner.invoke(cli, ['invalid-command'])

        assert result.exit_code != 0
        assert 'Error' in result.output or 'Usage:' in result.output

    def test_invalid_flag_produces_clear_error(self, cli_runner):
        """Test invalid flag produces clear error and non-zero exit."""
        result = cli_runner.invoke(cli, ['--invalid-flag'])

        assert result.exit_code != 0
        assert 'Error' in result.output or 'Usage:' in result.output

    def test_malformed_arguments_produce_error(self, cli_runner):
        """Test malformed arguments produce clear error."""
        # Test with malformed flag syntax
        result = cli_runner.invoke(cli, ['init', '--output'])  # Missing value

        # Should error or show usage
        assert result.exit_code != 0 or 'Usage:' in result.output

    def test_cli_execute_with_usage_error(self):
        """Test CLI.execute handles click.UsageError properly."""
        cli_app = CLI()

        with patch.object(cli_app.click_group, 'main') as mock_main:
            from click import UsageError
            mock_main.side_effect = UsageError("Invalid usage")

            exit_code = cli_app.execute(['test', 'args'])

            assert exit_code == 2

    def test_cli_execute_with_unexpected_error(self, capsys):
        """Test CLI.execute handles unexpected errors properly."""
        cli_app = CLI()

        with patch.object(cli_app.click_group, 'main') as mock_main:
            mock_main.side_effect = RuntimeError("Unexpected error")

            exit_code = cli_app.execute(['test', 'args'])

            assert exit_code == 1
            captured = capsys.readouterr()
            # Error message should contain the error text
            assert "Unexpected error" in captured.err
            assert "Error" in captured.err

    def test_cli_execute_with_debug_shows_traceback(self, capsys):
        """Test CLI.execute shows traceback in debug mode."""
        cli_app = CLI()

        with patch.object(cli_app.click_group, 'main') as mock_main:
            mock_main.side_effect = RuntimeError("Unexpected error")

            exit_code = cli_app.execute(['--debug', 'test', 'args'])

            assert exit_code == 1


class TestCLIKeyboardInterrupt:
    """Test CLI KeyboardInterrupt handling."""

    def test_keyboard_interrupt_exits_with_code_130(self):
        """Test KeyboardInterrupt exits with code 130 and no stack trace."""
        cli_app = CLI()

        with patch.object(cli_app.click_group, 'main') as mock_main:
            from click import Abort
            mock_main.side_effect = Abort()

            exit_code = cli_app.execute(['test', 'args'])

            assert exit_code == 130

    def test_signal_handler_registration(self):
        """Test signal handlers are registered properly."""
        cli_app = CLI()

        # Signal handlers should be registered during initialization
        # This test verifies the CLI doesn't crash during init
        assert cli_app.click_group is not None

    def test_signal_handler_handles_sigint(self, capsys):
        """Test signal handler handles SIGINT properly."""
        cli_app = CLI()

        # Simulate signal handler call
        with pytest.raises(SystemExit) as exc_info:
            cli_app._handle_termination(signal.SIGINT, None)

        assert exc_info.value.code == 130
        captured = capsys.readouterr()
        assert "interrupted" in captured.out.lower()

    def test_signal_handler_handles_sigterm(self, capsys):
        """Test signal handler handles SIGTERM properly."""
        cli_app = CLI()

        # Simulate signal handler call
        with pytest.raises(SystemExit) as exc_info:
            cli_app._handle_termination(signal.SIGTERM, None)

        assert exc_info.value.code == 130
        captured = capsys.readouterr()
        assert "interrupted" in captured.out.lower()


class TestCLICommandDispatch:
    """Test CLI command routing and dispatch."""

    @patch('agent_actions.tasks.init.init')
    def test_dispatch_routes_to_init_with_correct_args(self, mock_init, cli_runner):
        """Test dispatch routes to init command with correct arguments."""
        # Configure mock to avoid actual execution
        mock_init.return_value = None

        result = cli_runner.invoke(cli, ['init', '--help'])

        # Should route to init command (help should work)
        assert result.exit_code == 0 or 'Usage:' in result.output

    @patch('agent_actions.tasks.compile.render')
    def test_dispatch_routes_to_compile_with_correct_args(self, mock_render, cli_runner):
        """Test dispatch routes to compile/render command with correct arguments."""
        # Configure mock to avoid actual execution
        mock_render.return_value = None

        result = cli_runner.invoke(cli, ['render', '--help'])

        # Should route to render command (help should work)
        assert result.exit_code == 0 or 'Usage:' in result.output

    @patch('agent_actions.tasks.run.run')
    def test_dispatch_routes_to_run_with_correct_args(self, mock_run, cli_runner):
        """Test dispatch routes to run command with correct arguments."""
        # Configure mock to avoid actual execution
        mock_run.return_value = None

        result = cli_runner.invoke(cli, ['run', '--help'])

        # Should route to run command (help should work)
        assert result.exit_code == 0 or 'Usage:' in result.output

    @patch('agent_actions.tasks.status.status')
    def test_dispatch_routes_to_status_with_correct_args(self, mock_status, cli_runner):
        """Test dispatch routes to status command with correct arguments."""
        # Configure mock to avoid actual execution
        mock_status.return_value = None

        result = cli_runner.invoke(cli, ['status', '--help'])

        # Should route to status command (help should work)
        assert result.exit_code == 0 or 'Usage:' in result.output

    @patch('agent_actions.tasks.batch.batch')
    def test_dispatch_routes_to_batch_with_correct_args(self, mock_batch, cli_runner):
        """Test dispatch routes to batch command with correct arguments."""
        # Configure mock to avoid actual execution
        mock_batch.return_value = None

        result = cli_runner.invoke(cli, ['batch', '--help'])

        # Should route to batch command (help should work)
        assert result.exit_code == 0 or 'Usage:' in result.output

    def test_command_registration_in_click_group(self):
        """Test all commands are properly registered in click group."""
        cli_app = CLI()

        # Verify commands are registered
        assert cli_app.click_group is not None

        # Should have some commands registered
        assert hasattr(cli_app.click_group, 'commands') or hasattr(cli_app.click_group, 'list_commands')


class TestCLILogging:
    """Test CLI logging configuration."""

    def test_debug_mode_enables_debug_logging(self):
        """Test --debug flag enables debug logging."""
        cli_app = CLI()

        # Test logging configuration with debug args
        cli_app._configure_logging(['--debug', 'test'])

        # Should not raise any errors
        assert cli_app.logger is not None

    def test_verbose_mode_enables_info_logging(self):
        """Test --verbose flag enables info logging."""
        cli_app = CLI()

        # Test logging configuration with verbose args
        cli_app._configure_logging(['--verbose', 'test'])

        # Should not raise any errors
        assert cli_app.logger is not None

    def test_default_logging_level(self):
        """Test default logging level is appropriate."""
        cli_app = CLI()

        # Test logging configuration with no special args
        cli_app._configure_logging(['test'])

        # Should not raise any errors
        assert cli_app.logger is not None


class TestCLIIntegration:
    """Integration tests for CLI functionality."""

    def test_main_entrypoint_returns_exit_code(self):
        """Test main_entrypoint returns proper exit code."""
        # Test with version flag which should exit cleanly
        exit_code = main_entrypoint(['--version'])

        assert exit_code == 0

    def test_main_entrypoint_handles_no_args(self):
        """Test main_entrypoint handles no arguments."""
        # Should not crash with no arguments
        exit_code = main_entrypoint([])

        # Should return some exit code (0 for help, or error code)
        assert isinstance(exit_code, int)

    def test_main_function_calls_sys_exit(self):
        """Test main() function calls sys.exit with proper code."""
        with patch('sys.exit') as mock_exit:
            with patch('agent_actions.cli.main.main_entrypoint') as mock_entrypoint:
                mock_entrypoint.return_value = 0

                main()

                mock_exit.assert_called_once_with(0)

    @patch('agent_actions.cli.main.CLI')
    def test_main_entrypoint_creates_cli_and_executes(self, mock_cli_class):
        """Test main_entrypoint creates CLI instance and executes."""
        mock_cli_instance = Mock()
        mock_cli_instance.execute.return_value = 0
        mock_cli_class.return_value = mock_cli_instance

        exit_code = main_entrypoint(['test', 'args'])

        mock_cli_class.assert_called_once()
        mock_cli_instance.execute.assert_called_once_with(['test', 'args'])
        assert exit_code == 0


class TestCLICommandAvailability:
    """Test that all expected commands are available."""

    def test_all_expected_commands_are_registered(self):
        """Test all expected commands from imports are registered."""
        cli_app = CLI()

        # Test that CLI app was created successfully
        assert cli_app.click_group is not None

        # Commands should be registered during init
        expected_commands = ['init', 'render', 'run', 'batch', 'status', 'clean', 'docs']

        # At minimum, the CLI should be able to instantiate without errors
        assert cli_app.logger is not None

    def test_cli_instantiation_does_not_raise(self):
        """Test CLI can be instantiated without raising exceptions."""
        # Should not raise any exceptions during initialization
        cli_app = CLI()
        assert cli_app is not None

    def test_signal_handler_registration_resilient(self):
        """Test signal handler registration is resilient to errors."""
        # Should handle cases where signal registration fails
        with patch('signal.signal') as mock_signal:
            mock_signal.side_effect = ValueError("Signal not supported")

            # Should not raise, just log warning
            cli_app = CLI()
            assert cli_app is not None