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
    """The workflow, as ``-w/--workflow`` or ``-a/--agent``, passed to the command as *name*."""
    return click.option("-w", "--workflow", "-a", "--agent", name, required=required, help=help)


_A_IS_DEPRECATED = (
    "Warning: -a is deprecated in 'agac {command}', where it names the action, and will "
    "name the workflow as it does in the other commands. Type -A or --action for the "
    "action, and -w or --workflow for the workflow."
)


def _warn_a_is_deprecated(
    ctx: click.Context, _param: click.Parameter, value: str | None
) -> str | None:
    if value is not None and not ctx.resilient_parsing:
        click.echo(_A_IS_DEPRECATED.format(command=ctx.info_name), err=True)
    return value


def action_option(*, required: bool = False, help: str) -> Callable:
    """The action, as ``-A/--action``, for a command that used to read it from ``-a``.

    ``-a`` still names the action there, with a warning on stderr. The option is eager, so
    the warning is printed before ``--help`` and before an error in any other option.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, action: str | None, deprecated_action: str | None, **kwargs: Any):
            if action is not None and deprecated_action is not None:
                raise click.UsageError("-a and -A both name the action: give -A alone.")
            if action is None:
                action = deprecated_action
            if required and action is None:
                raise click.UsageError("Missing option '-A' / '--action'.")
            return func(*args, action=action, **kwargs)

        shown = f"{help}  [required]" if required else help
        deprecated = click.option(
            "-a",
            "deprecated_action",
            default=None,
            hidden=True,
            is_eager=True,
            callback=_warn_a_is_deprecated,
        )
        return click.option("-A", "--action", default=None, help=shown)(deprecated(wrapper))

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
