"""CLI decorators for agent-actions commands."""

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from agent_actions.errors.base import AgentActionsError
from agent_actions.utils.project_root import ensure_in_project


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
                    **kwargs,
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


def requires_project(func):
    """Inject ``project_root`` kwarg. Banner only when cwd ≠ project_root
    (``📁 Project root: .`` from inside the project is just noise)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        project_root = ensure_in_project()
        display = _format_project_root_display(project_root)
        if display != ".":
            click.echo(f"📁 Project root: {display}", err=True)
        return func(*args, project_root=project_root, **kwargs)

    return wrapper


def _format_project_root_display(project_root: Path) -> str:
    return "." if Path.cwd() == project_root else str(project_root)
