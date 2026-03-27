"""Main entry point for the Agent Actions CLI."""

import logging
import signal
import sys
from collections.abc import Sequence

import click

from agent_actions.__version__ import __version__
from agent_actions.cli.clean import clean_cli as clean
from agent_actions.cli.compile import compile, render
from agent_actions.cli.docs import docs
from agent_actions.cli.init import init
from agent_actions.cli.inspect import inspect
from agent_actions.cli.list_udfs import list_udfs_cmd
from agent_actions.cli.preview import preview
from agent_actions.cli.run import run
from agent_actions.cli.schema import schema
from agent_actions.cli.skills import skills
from agent_actions.cli.status import status
from agent_actions.errors import ProjectNotFoundError
from agent_actions.llm.batch.batch_cli import batch
from agent_actions.logging import LoggerFactory, LoggingConfig, fire_event
from agent_actions.logging.errors import format_user_error
from agent_actions.logging.events import (
    CLIArgumentParsingEvent,
    CLIInitCompleteEvent,
    CLIInitStartEvent,
)
from agent_actions.utils.safe_format import format_exception_chain_for_debug
from agent_actions.validation.validate_udfs import validate_udfs_cmd


class CLI:
    """Agent Actions CLI application."""

    def __init__(self) -> None:
        fire_event(CLIInitStartEvent())
        self.logger = logging.getLogger(__name__)
        self.click_group = self._create_click_group()
        self._register_commands()
        self._register_signal_handlers()
        fire_event(CLIInitCompleteEvent(command="agent-actions"))

    def _create_click_group(self) -> click.Group:
        cli_instance = self

        @click.group(name="agent-actions")
        @click.version_option(
            version=__version__, prog_name="Agent Actions CLI", message="%(prog)s v%(version)s"
        )
        @click.option(
            "--debug",
            is_flag=True,
            help="Enable debug mode with verbose logging and source file/line references",
        )
        @click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
        @click.option("-q", "--quiet", is_flag=True, help="Show only warnings and errors")
        def group(debug: bool, verbose: bool, quiet: bool) -> None:
            """Agent Actions CLI tool for managing and running agent workflows."""
            cli_instance._configure_logging(debug=debug, verbose=verbose, quiet=quiet)

        return group

    def _register_commands(self) -> None:
        self.logger.debug("Registering CLI commands")
        self.click_group.add_command(clean)
        self.click_group.add_command(compile)
        self.click_group.add_command(init)
        self.click_group.add_command(inspect)
        self.click_group.add_command(preview)
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
        try:
            signal.signal(signal.SIGINT, self._handle_termination)
            signal.signal(signal.SIGTERM, self._handle_termination)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, self._handle_termination)
            self.logger.debug("Signal handlers registered successfully")
        except (AttributeError, ValueError) as e:
            self.logger.warning("Failed to register signal handlers: %s", e, exc_info=True)

    def _handle_termination(self, signum: int, _frame) -> None:
        signal_name = signal.Signals(signum).name
        self.logger.info("Received termination signal: %s", signal_name)
        click.echo(f"\nOperation interrupted by {signal_name}. Exiting gracefully...")
        sys.exit(130)

    def _configure_logging(
        self, debug: bool = False, verbose: bool = False, quiet: bool = False
    ) -> None:
        config = LoggingConfig.from_environment()
        if debug:
            config.default_level = "DEBUG"
        elif verbose:
            config.default_level = "INFO"
        elif quiet:
            config.default_level = "WARNING"

        LoggerFactory.initialize(
            config=config,
            verbose=debug or verbose,
            quiet=quiet,
            force=True,
        )
        self.logger = LoggerFactory.get_logger("cli")

    def execute(self, argv: Sequence[str] | None = None) -> int:
        try:
            if argv is None:
                argv = sys.argv[1:]
            # Initialize logging with defaults; Click callback overrides with flags
            self._configure_logging()
            self.logger.info(
                "Starting agent-actions CLI", extra={"version": __version__, "cli_args": argv}
            )
            command = argv[0] if argv else "agent-actions"
            fire_event(CLIArgumentParsingEvent(command=command, args={"argv": list(argv)}))
            result = self.click_group.main(argv, standalone_mode=False)
            if isinstance(result, int) and result != 0:
                return result
            self.logger.info("CLI execution completed successfully")
            return 0
        except click.Abort:
            self.logger.info("Operation aborted by user")
            return 130
        except click.UsageError as e:
            self.logger.warning("Usage error: %s", e)
            click.echo(f"Error: {str(e)}", err=True)
            return 2
        except click.ClickException as e:
            click.echo(f"Error: {e.format_message()}", err=True)
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
            click.echo(click.style("Error: ", fg="red", bold=True) + error_msg, err=True)
            return 1
        except Exception as e:
            # Safety net: @handles_user_errors only catches AgentActionsError.
            # This catch-all ensures other exceptions are still formatted
            # nicely for users (raw tracebacks only shown with --debug).
            context = {
                "command": argv[0] if argv else "agent-actions",
                "operation": "cli_execution",
            }

            error_message = format_user_error(e, context)
            click.echo(f"Error: {error_message}", err=True)

            if "--debug" in (argv or []):
                self.logger.exception("CLI execution failed", extra={"error": str(e)})
                self.logger.debug("Debug Information:")
                self.logger.debug("Exception Chain:")
                self.logger.debug("%s", format_exception_chain_for_debug(e))
            return 1


def main_entrypoint(argv: Sequence[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    app = CLI()
    return app.execute(argv)


def main() -> None:
    sys.exit(main_entrypoint())


class _LazyCLI:
    """Lazy proxy that defers CLI() instantiation until the click group is accessed."""

    def __init__(self):
        self._cli = None

    def __getattr__(self, name):
        if self._cli is None:
            self._cli = CLI().click_group
        return getattr(self._cli, name)

    def __call__(self, *args, **kwargs):
        if self._cli is None:
            self._cli = CLI().click_group
        return self._cli(*args, **kwargs)


cli = _LazyCLI()

if __name__ == "__main__":
    main()
