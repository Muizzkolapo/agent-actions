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
    """
    Decorator that standardizes error handling for CLI commands.

    Catches all exceptions, formats them user-friendly via format_user_error(),
    and raises ClickException. This eliminates try/except boilerplate in every
    command function.

    Args:
        command_name: Name of the command for error context (e.g., 'run', 'init')
        **extra_context: Additional context keys to include in error messages

    Usage:
        @click.command()
        @handles_user_errors('run')
        def run(agent: str, user_code: str):
            # No try/except needed - just write happy path!
            command = RunCommand(agent, user_code)
            command.execute()

        @click.command()
        @handles_user_errors('init', template='default')
        def init(project_name: str):
            # Extra context included automatically
            command = InitCommand(project_name)
            command.execute()

    Raises:
        click.ClickException: All exceptions are caught, formatted, and re-raised
                             as ClickException with user-friendly messages

    Example:
        >>> @handles_user_errors('status')
        >>> def status(agent: str):
        >>>     # If this raises ValidationError, it's automatically formatted
        >>>     raise ValidationError("Agent not found")
        >>> # User sees: "❌ Validation failed: Agent not found"
        >>> # Instead of raw Python traceback

    Note:
        - ClickExceptions are NOT double-wrapped (passed through unchanged)
        - All CLI kwargs are automatically included in error context
        - Works seamlessly with other decorators (e.g., @requires_project)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except click.ClickException:
                # Don't double-wrap ClickExceptions - pass through unchanged
                raise
            except Exception as e:
                # Check if error was already displayed by workflow handler
                if getattr(e, "_already_displayed", False):
                    # Error was already printed with structured format
                    # Just exit with error code, no duplicate message
                    raise SystemExit(1) from None

                from agent_actions.logging.errors import format_user_error

                # Merge command context with extra context and all kwargs
                context = {
                    "command": command_name,
                    **extra_context,
                    **kwargs,  # Include all CLI arguments in error context
                }
                error_message = format_user_error(e, context)
                # Use 'from None' to suppress exception chaining and prevent
                # Python traceback from being displayed to users
                raise click.ClickException(error_message) from None

        return wrapper

    return decorator


def requires_project(func):
    """
    Decorator for CLI commands that require being in a project.

    Automatically finds the project root and changes to that directory
    before executing the command. Provides user feedback about the
    detected project root.

    This allows commands to be run from any subdirectory within a project.

    Usage:
        @click.command()
        @requires_project
        def run(...):
            # Command implementation
            # CWD is now project root
            pass

    Raises:
        ProjectNotFoundError: If not in a project (propagated to CLI error handler)

    Example:
        >>> # Project structure:
        >>> # /my-project/
        >>> #   agent_actions.yml
        >>> #   src/utils/
        >>>
        >>> # Running from /my-project/src/utils/
        >>> $ agac run -a my_agent
        >>> 📁 Project root: ../..
        >>> ✅ Running workflow...
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Find and validate we're in a project
        # This raises ProjectNotFoundError if not found
        project_root = ensure_in_project()

        # Show user where project root was detected
        # Use relative path if within CWD, otherwise absolute
        cwd = Path.cwd()
        try:
            rel_path = project_root.relative_to(cwd)
            # Show "./" prefix for clarity, or just "." if at root
            display_path = f"./{rel_path}" if str(rel_path) != "." else "."
        except ValueError:
            # Not relative to CWD (project root is outside current directory)
            # Use absolute path
            display_path = str(project_root)

        click.echo(f"📁 Project root: {display_path}")

        # Change to project root for command execution
        original_cwd = os.getcwd()
        os.chdir(project_root)

        try:
            # Execute the wrapped command
            return func(*args, **kwargs)
        finally:
            # Always restore original directory (defensive programming)
            # This ensures CWD is restored even if command fails
            os.chdir(original_cwd)

    return wrapper
