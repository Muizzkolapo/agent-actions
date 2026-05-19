"""Top-level ``agac example`` command group."""

import logging
from pathlib import Path

import click
import yaml

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.cli.init import _fetch_example, _print_available_examples
from agent_actions.utils.constants import PROJECT_NAME_KEY

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
    dest_name = project_name or name
    out = Path(output_dir) if output_dir else Path.cwd()
    dest = out / dest_name
    _fetch_example(name, dest, force=force)

    # Inject project_name into the example's agent_actions.yml
    config_file = dest / "agent_actions.yml"
    if config_file.exists():
        try:
            with open(config_file, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            config[PROJECT_NAME_KEY] = dest_name
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Could not inject project_name into %s: %s", config_file, exc)

    click.echo(f"Created project from example '{name}': {dest}")
    click.echo("\nNext steps:")
    click.echo(f"  cd {dest_name}")
    click.echo("  agac run")
