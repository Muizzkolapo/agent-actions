"""Top-level ``agac example`` command group."""

import logging

import click

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.cli.init import _install_example, _print_available_examples

logger = logging.getLogger(__name__)


@click.group()
def example() -> None:
    """Browse and install example projects.

    \b
    Examples:
        agac example list
        agac example install contract_reviewer
        agac example install contract_reviewer my_project
    """


@example.command("list")
@handles_user_errors("example list")
def example_list() -> None:
    """List available example projects from GitHub."""
    _print_available_examples()


@example.command("install")
@click.argument("name")
@click.argument("project_name", required=False, default=None)
@click.option(
    "-o", "--output-dir", help="Directory to create the project in (default: current directory)"
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Force project creation even if directory exists",
)
@handles_user_errors("example install")
def example_install(
    name: str,
    project_name: str | None = None,
    output_dir: str | None = None,
    force: bool = False,
) -> None:
    """Install an example project from GitHub.

    \b
    Examples:
        agac example install contract_reviewer
        agac example install contract_reviewer my_project
    """
    _install_example(name, project_name, output_dir, force, log=logger)
