"""
CLI decorators for agent-actions commands.
"""

import os
import functools
from pathlib import Path
from typing import Callable, Any
import click

from agent_actions.cli.project_root import ensure_in_project


def handles_user_errors(command_name: str, **extra_context: Any) -> Callable:
    """Catch exceptions, format via format_user_error(), and re-raise as ClickException."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except click.ClickException:
                raise
            except Exception as e:
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

        return wrapper

    return decorator


def requires_project(func):
    """Find project root, chdir into it, and restore CWD after the command."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        project_root = ensure_in_project()

        cwd = Path.cwd()
        try:
            rel_path = project_root.relative_to(cwd)
            display_path = f"./{rel_path}" if str(rel_path) != "." else "."
        except ValueError:
            display_path = str(project_root)

        click.echo(f"📁 Project root: {display_path}", err=True)

        original_cwd = os.getcwd()
        os.chdir(project_root)

        try:
            return func(*args, **kwargs)
        finally:
            os.chdir(original_cwd)

    return wrapper
