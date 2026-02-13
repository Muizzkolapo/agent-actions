"""
Main entry point for the Agent Actions CLI.

This module provides the primary entry point for the CLI application,
handling command registration, initialization, and execution.
"""

import logging
import signal
import sys
from typing import Optional, Sequence, List

import click

from agent_actions.cli.compile import render, compile
from agent_actions.cli.docs import docs  # Documentation generation and serving
from agent_actions.cli.init import init
from agent_actions.cli.inspect import inspect  # Workflow inspection commands
from agent_actions.cli.list_udfs import list_udfs_cmd
from agent_actions.cli.preview import preview  # Data preview for SQLite storage
from agent_actions.cli.run import run
from agent_actions.cli.schema import schema
from agent_actions.cli.skills import skills  # Skills installation for Claude/Codex
from agent_actions.cli.status import status
from agent_actions.cli.clean import clean_cli as clean
from agent_actions.errors import ProjectNotFoundError
from agent_actions.llm.batch.batch_cli import (
    batch,  # CLI command group for batch processing operations
)
from agent_actions.logging import LoggerFactory, LoggingConfig, fire_event
from agent_actions.logging.events import (
    CLIInitStartEvent,
    CLIInitCompleteEvent,
    CLIArgumentParsingEvent,
)
from agent_actions.validation.validate_udfs import validate_udfs_cmd
from agent_actions.logging.errors import format_user_error
from agent_actions.utils.safe_format import format_exception_chain_for_debug
from agent_actions.__version__ import __version__


class CLI:
    """Agent Actions CLI application."""

    def __init__(self) -> None:
        """Initialize the CLI application."""
        fire_event(CLIInitStartEvent())
        # Use standard logger initially; will be replaced with LoggerFactory logger
        # after _configure_logging is called
        self.logger = logging.getLogger(__name__)
        self.click_group = self._create_click_group()
        self._register_commands()
        self._register_signal_handlers()
        fire_event(CLIInitCompleteEvent(command="agent-actions"))

    def _create_click_group(self) -> click.Group:
        """Create the main click group with global options."""

        @click.group(name="agent-actions")
        @click.version_option(version=__version__)
        @click.option(
            "--debug",
            is_flag=True,
            help="Enable debug mode with verbose logging and source file/line references",
        )
        @click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
        @click.option("-q", "--quiet", is_flag=True, help="Show only warnings and errors")
        def group(debug: bool, verbose: bool, quiet: bool) -> None:
            """Agent Actions CLI tool for managing and running agent workflows."""

        return group

    def _register_commands(self) -> None:
        """Register all available commands with the CLI."""
        self.logger.debug("Registering CLI commands")
        self.click_group.add_command(clean)
        self.click_group.add_command(compile)  # Alias for render
        self.click_group.add_command(init)
        self.click_group.add_command(inspect)
        self.click_group.add_command(preview)  # Preview data from SQLite storage
        self.click_group.add_command(render)
        self.click_group.add_command(run)
        self.click_group.add_command(batch)
        self.click_group.add_command(schema)
        self.click_group.add_command(status)
        self.click_group.add_command(list_udfs_cmd)
        self.click_group.add_command(validate_udfs_cmd)
        self.click_group.add_command(docs)
        self.click_group.add_command(skills)

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_termination)
            signal.signal(signal.SIGTERM, self._handle_termination)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, self._handle_termination)
            self.logger.debug("Signal handlers registered successfully")
        except (AttributeError, ValueError) as e:
            self.logger.warning("Failed to register signal handlers: %s", str(e))

    def _handle_termination(self, signum: int, _frame) -> None:
        """
        Handle termination signals gracefully.

        Args:
            signum: Signal number
            _frame: Current stack frame (unused but required by signal handler signature)
        """
        signal_name = signal.Signals(signum).name
        self.logger.info("Received termination signal: %s", signal_name)
        print(f"\nOperation interrupted by {signal_name}. Exiting gracefully...")
        sys.exit(130)

    def _configure_logging(self, argv: List[str]) -> None:
        """
        Configure logging based on command-line arguments.

        Uses the unified LoggerFactory which routes all logging through
        the event system for consistent structured output.

        Args:
            argv: Command-line arguments
        """
        debug_mode = "--debug" in argv
        verbose_mode = "--verbose" in argv or "-v" in argv
        quiet_mode = "--quiet" in argv or "-q" in argv

        # Initialize unified logging system
        # Workflow-specific settings (output_dir, workflow_name) will be
        # set by the run command when a workflow is executed
        config = LoggingConfig.from_environment()
        if debug_mode:
            config.default_level = "DEBUG"
        elif verbose_mode:
            config.default_level = "INFO"
        elif quiet_mode:
            config.default_level = "WARN"

        LoggerFactory.initialize(
            config=config,
            verbose=debug_mode or verbose_mode,
            quiet=quiet_mode,
            force=True,
        )
        self.logger = LoggerFactory.get_logger("cli")

    def _show_version_and_exit(self) -> int:
        """Display version information and return exit code."""
        print(f"Agent Actions CLI v{__version__}")
        return 0

    def execute(self, argv: Optional[Sequence[str]] = None) -> int:
        """
        Execute the CLI application with the provided arguments.

        Args:
            argv: Command-line arguments (uses sys.argv if None)

        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        try:
            if argv is None:
                argv = sys.argv[1:]
            if "--version" in argv or "-V" in argv:
                return self._show_version_and_exit()
            self._configure_logging(argv)
            self.logger.info(
                "Starting agent-actions CLI", extra={"version": __version__, "cli_args": argv}
            )
            # Fire CLI argument parsing event
            command = argv[0] if argv else "agent-actions"
            fire_event(CLIArgumentParsingEvent(command=command, args={"argv": list(argv)}))
            self.click_group.main(argv, standalone_mode=False)
            self.logger.info("CLI execution completed successfully")
            return 0
        except click.Abort:
            self.logger.info("Operation aborted by user")
            return 130
        except click.UsageError as e:
            self.logger.error("Usage error: %s", str(e))
            print(f"Error: {str(e)}", file=sys.stderr)
            return 2
        except click.ClickException as e:
            # ClickException already has formatted message from decorator
            # Just print it without re-formatting
            print(f"Error: {e.format_message()}", file=sys.stderr)
            return e.exit_code if hasattr(e, "exit_code") else 1
        except ProjectNotFoundError as e:
            self.logger.info("Not in project directory")
            context = e.context if hasattr(e, "context") else {}
            marker_file = context.get("marker_file", "agent_actions.yml")
            search_path = context.get("search_path", "unknown")
            solution_1 = context.get(
                "solution_1", "Navigate to your agent-actions project directory"
            )
            solution_2 = context.get("solution_2", "Run 'agac init' to create a new project")
            error_msg = (
                f"Not in an agent-actions project\n\n"
                f"Could not find '{marker_file}' in current directory "
                f"or any parent directory.\n\n"
                f"Current directory: {search_path}\n\n"
                f"Solutions:\n  1. {solution_1}\n  2. {solution_2}"
            )
            print(click.style("Error: ", fg="red", bold=True) + error_msg, file=sys.stderr)
            return 1
        except Exception as e:
            context = {
                "command": argv[0] if argv else "agent-actions",
                "operation": "cli_execution",
            }

            # Format and print the user-friendly error message
            error_message = format_user_error(e, context)
            print(f"Error: {error_message}", file=sys.stderr)

            # Only log details in debug mode
            if "--debug" in (argv or []):
                self.logger.exception("CLI execution failed", extra={"error": str(e)})
                self.logger.debug("Debug Information:")
                self.logger.debug("Exception Chain:")
                self.logger.debug("%s", format_exception_chain_for_debug(e))
            return 1


def main_entrypoint(argv: Optional[Sequence[str]] = None) -> int:
    """
    Main entry point for the CLI application.

    Args:
        argv: Command-line arguments (uses sys.argv if None)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    app = CLI()
    return app.execute(argv)


def main() -> None:
    """
    Entry point for the CLI tool when run from the command line.
    Exits with appropriate status code.
    """
    sys.exit(main_entrypoint())


# Module-level CLI instance for test compatibility
# Tests use cli_runner.invoke(cli, ...) pattern
cli = CLI().click_group

if __name__ == "__main__":
    main()
