"""CLI decorators for agent-actions commands."""

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from agent_actions.errors.base import AgentActionsError
from agent_actions.utils.project_root import ensure_in_project

# An action the user typed is not the action an error is about.
_NOT_ERROR_CONTEXT = frozenset({"action_name"})


def handles_user_errors(command_name: str, **extra_context: Any) -> Callable:
    """Catch exceptions, format via format_user_error(), and re-raise as ClickException."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except click.ClickException:
                raise
            except AgentActionsError as e:
                # Expected application errors — prettify for CLI
                if getattr(e, "_already_displayed", False):
                    raise click.exceptions.Exit(1) from None
                from agent_actions.logging.errors import format_user_error

                context = {
                    "command": command_name,
                    **extra_context,
                    **{k: v for k, v in kwargs.items() if k not in _NOT_ERROR_CONTEXT},
                }
                error_message = format_user_error(e, context)
                raise click.ClickException(error_message) from None
            except Exception as e:
                # Unexpected errors (bugs) — preserve traceback for debugging
                if getattr(e, "_already_displayed", False):
                    raise click.exceptions.Exit(1) from None
                raise

        return wrapper

    return decorator


def workflow_option(
    name: str = "agent",
    *,
    required: bool = True,
    help: str = "Workflow name: its configuration file name without path or extension",
) -> Callable:
    """The workflow, as ``-w/--workflow`` or ``-a``, passed to the command as *name*."""
    return click.option("-w", "--workflow", "-a", name, required=required, help=help)


SANDBOX_READ_HELP = "Read what sandbox runs (agac run --sandbox) stored, not what real runs stored"


def sandbox_option(
    help: str = SANDBOX_READ_HELP, note: str = "reading the sandbox output"
) -> Callable:
    """``--sandbox``: the command runs in sandbox mode and says so on stderr.

    The mode is held on the Click context, so a group's subcommand runs in it too.
    """

    def decorator(func: Callable) -> Callable:
        @click.option("--sandbox", is_flag=True, default=False, help=help)
        @functools.wraps(func)
        def wrapper(*args: Any, sandbox: bool = False, **kwargs: Any) -> Any:
            if sandbox:
                from agent_actions.config.sandbox import sandbox_mode

                click.get_current_context().with_resource(sandbox_mode(True))
                click.echo(f"{click.style('SANDBOX', fg='yellow', bold=True)}: {note}", err=True)
            return func(*args, **kwargs)

        return wrapper

    return decorator


SCENARIO_HELP = (
    "The scenario the mock follows, a preset or a scenario file. Default: "
    "sandbox.<workflow>.yml at the project root, else sandbox.yml, else happy"
)


def scenario_option(help: str = f"With --sandbox: {SCENARIO_HELP}") -> Callable:
    """``--scenario``: the faults the sandbox mock follows; it needs sandbox mode above it."""

    def decorator(func: Callable) -> Callable:
        @click.option("--scenario", default=None, metavar="happy|chaos|PATH", help=help)
        @functools.wraps(func)
        def wrapper(*args: Any, scenario: str | None = None, **kwargs: Any) -> Any:
            from agent_actions.config import sandbox

            if scenario is not None and not sandbox.is_active():
                raise click.UsageError("--scenario needs --sandbox")
            click.get_current_context().with_resource(sandbox.scenario_choice(scenario))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def requires_project(func):
    """Inject ``project_root`` kwarg. Banner only when cwd ≠ project_root
    (``📁 Project root: .`` from inside the project is just noise)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, project_root=enter_project(), **kwargs)

    return wrapper


def enter_project() -> Path:
    """The project root, or exit as ``requires_project`` does; the banner as it prints it.

    For a group callback, which Click runs before a subcommand's ``--help``: called
    there only when the group itself runs.
    """
    project_root = ensure_in_project()
    display = _format_project_root_display(project_root)
    if display != ".":
        click.echo(f"📁 Project root: {display}", err=True)
    return project_root


def _format_project_root_display(project_root: Path) -> str:
    return "." if Path.cwd() == project_root else str(project_root)
