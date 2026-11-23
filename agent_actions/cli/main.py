"""Main entry point for the Agent Actions CLI."""

import importlib
import logging
import signal
import sys
from collections.abc import Callable, Sequence
from functools import partial
from gettext import gettext as _
from pathlib import Path

import click
from click.utils import make_default_short_help

from agent_actions.__version__ import __version__
from agent_actions.config.path_config import find_project_root_dir, load_project_config
from agent_actions.errors import ConfigValidationError, ProjectNotFoundError
from agent_actions.logging.config import LoggingConfig, report_unread_env_vars
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.errors import format_user_error
from agent_actions.logging.events import (
    CLIArgumentParsingEvent,
    CLIInitCompleteEvent,
    CLIInitStartEvent,
)
from agent_actions.logging.factory import LoggerFactory
from agent_actions.utils.safe_format import format_exception_chain_for_debug

# name -> ("module:attribute", summary). A command is imported only when it is
# looked up; `agac --help` lists the others by their summary, which a test holds
# equal to the command's own short help.
_COMMANDS: dict[str, tuple[str, str]] = {
    "clean": ("agent_actions.cli.clean:clean_cli", "Remove a workflow's working directories."),
    "dispositions": (
        "agent_actions.cli.dispositions:dispositions",
        "Inspect record-level processing dispositions per action.",
    ),
    "init": ("agent_actions.cli.init:init", "Initialize a new Agent Actions project."),
    "inspect": (
        "agent_actions.cli.inspect:inspect",
        "Inspect workflow structure and validation status.",
    ),
    "preview": (
        "agent_actions.cli.preview:preview",
        "Preview data stored in the SQLite storage backend.",
    ),
    "retry": (
        "agent_actions.cli.retry:retry",
        "Retry failed/exhausted records from a specific action forward.",
    ),
    "run": ("agent_actions.cli.run:run", "Run agents with a specified agent configuration."),
    "batch": (
        "agent_actions.llm.batch.batch_cli:batch",
        "CLI command group for batch processing operations.",
    ),
    "schema": (
        "agent_actions.cli.schema:schema",
        "Display input and output schemas for all actions in a workflow.",
    ),
    "status": ("agent_actions.cli.status:status", "Display the status of an agent workflow."),
    "list-udfs": (
        "agent_actions.cli.list_udfs:list_udfs_cmd",
        "List all discovered User-Defined Functions (UDFs).",
    ),
    "validate-udfs": (
        "agent_actions.validation.validate_udfs:validate_udfs_cmd",
        "Validate all UDF references in config without running the workflow.",
    ),
    "docs": ("agent_actions.cli.docs:docs", "Build and serve workflow documentation."),
    "example": ("agent_actions.cli.example:example", "Browse and install example projects."),
    "export": (
        "agent_actions.cli.export:export",
        "Write a workflow's declared outputs to their database tables.",
    ),
    "expect": ("agent_actions.cli.expect:expect", "Inspect expectation rules and verdicts."),
    "skills": (
        "agent_actions.cli.skills:skills",
        "Manage AI coding assistant skills (Claude Code / OpenAI Codex).",
    ),
    "traces": (
        "agent_actions.cli.traces:traces",
        "Print the prompt, context and response an action's records were run with.",
    ),
    "records": (
        "agent_actions.cli.records:records",
        "Print the records an action stored, as a JSON list.",
    ),
    "usage": (
        "agent_actions.cli.usage:usage",
        "Show the tokens each action's model calls used, and an estimated cost.",
    ),
}


class _LazyGroup(click.Group):
    """A group that imports a command added with ``add_lazy_command`` on first lookup.

    ``commands`` holds only the commands imported so far; ``list_commands`` and
    ``get_command`` see them all.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lazy_commands: dict[str, tuple[str, str]] = {}

    def add_lazy_command(self, name: str, import_path: str, summary: str) -> None:
        self.lazy_commands[name] = (import_path, summary)

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted({*self.commands, *self.lazy_commands})

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name not in self.commands and cmd_name in self.lazy_commands:
            module_name, attribute = self.lazy_commands[cmd_name][0].split(":")
            self.add_command(getattr(importlib.import_module(module_name), attribute), cmd_name)
        return super().get_command(ctx, cmd_name)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Click's listing, shortening a command not yet imported from its summary."""
        entries: list[tuple[str, Callable[[int], str]]] = []
        for name in self.list_commands(ctx):
            if name not in self.commands and name in self.lazy_commands:
                summary = self.lazy_commands[name][1]
                entries.append((name, partial(make_default_short_help, summary)))
                continue
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden:
                continue
            entries.append((name, cmd.get_short_help_str))
        if entries:
            limit = formatter.width - 6 - max(len(name) for name, _short_help in entries)
            rows = [(name, short_help(limit)) for name, short_help in entries]
            with formatter.section(_("Commands")):
                formatter.write_dl(rows)


class CLI:
    """Agent Actions CLI application."""

    def __init__(self) -> None:
        fire_event(CLIInitStartEvent())
        self.logger = logging.getLogger(__name__)
        # The project's logging: block, resolved once per execute() so the
        # pre-dispatch init and the Click callback share it (and its reports).
        self._logging_base: LoggingConfig | None = None
        self.click_group = self._create_click_group()
        self._register_commands()
        self._register_signal_handlers()
        fire_event(CLIInitCompleteEvent(command="agent-actions"))

    def _create_click_group(self) -> _LazyGroup:
        cli_instance = self

        @click.group(name="agent-actions", cls=_LazyGroup)
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
        for name, (import_path, summary) in _COMMANDS.items():
            self.click_group.add_lazy_command(name, import_path, summary)

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
        base = self._logging_base or self._resolve_logging_base()
        config = LoggingConfig.from_environment(base)
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

    @staticmethod
    def _resolve_logging_base() -> LoggingConfig:
        """The ``logging:`` block of the project at cwd; the defaults outside one.

        A project file that does not load is reported on stderr and the defaults
        stand: the commands that read the project fail on it on their own, and
        ``--help``, ``--version`` and ``agac init`` never read it.
        """
        report_unread_env_vars()
        project_root = find_project_root_dir()
        if project_root is None:
            return LoggingConfig()
        try:
            project_config = load_project_config(project_root)
        except ConfigValidationError as e:
            sys.stderr.write(
                f"agent_actions: logging: not read from the project config: "
                f"{e.context['reason']}; using the default logging config\n"
            )
            return LoggingConfig()
        return LoggingConfig.from_project_config(project_config)

    def execute(self, argv: Sequence[str] | None = None) -> int:
        try:
            if argv is None:
                argv = sys.argv[1:]
            self._logging_base = self._resolve_logging_base()
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
            self.logger.warning("Usage error: %s", e.format_message())
            click.echo(f"Error: {e.format_message()}", err=True)
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
        finally:
            self._logging_base = None


def _warn_shadowed_project_root(chosen: Path, shadowed: list[Path]) -> None:
    """Warn once that a nested ``agent_actions.yml`` was passed over.

    Emitted at the CLI layer (not inside the dependency-free resolver, which
    runs ~4×/invocation before logging boots) so the message fires exactly
    once and names both the chosen outermost root and the shadowed nested
    marker(s).
    """
    nested = "\n".join(f"    - {p}" for p in shadowed)
    click.echo(
        click.style("Warning: ", fg="yellow", bold=True)
        + "nested 'agent_actions.yml' shadowed by an outer project.\n"
        + f"  Using outermost project root: {chosen}\n"
        + f"  Ignoring nested marker(s):\n{nested}",
        err=True,
    )


def main_entrypoint(argv: Sequence[str] | None = None) -> int:
    from dotenv import load_dotenv

    from agent_actions.config.path_config import find_project_root_dir_with_shadow

    project_root, shadowed = find_project_root_dir_with_shadow()
    if shadowed and project_root is not None:
        _warn_shadowed_project_root(project_root, shadowed)
    if project_root:
        env_path = project_root / ".env"
        if env_path.is_file():
            load_dotenv(env_path)
    else:
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
