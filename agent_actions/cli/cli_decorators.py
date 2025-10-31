"""
CLI decorators for agent-actions commands.

This module provides decorators that enhance CLI commands with additional
functionality such as automatic project root detection.
"""

import os
import functools
from pathlib import Path
import click

from agent_actions.utilities.project_root import ensure_in_project


def requires_project(func):
    """
    Decorator for CLI commands that require being in a project.

    Automatically finds the project root and changes to that directory
    before executing the command. Provides user feedback about the
    detected project root.

    This allows commands to be run from any subdirectory within a project,
    similar to how git, dbt, and npm work.

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
        >>> $ agent-actions run -a my_agent
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
