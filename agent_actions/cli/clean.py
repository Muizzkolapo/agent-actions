"""Clean command for the Agent Actions CLI."""

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm.realtime.cleaner import Cleaner
from agent_actions.validation.clean_validator import CleanCommandArgs


@click.command(
    name="clean",
    help=(
        "Remove temporary directories created by an agent. "
        "By default removes source and target directories only."
    ),
)
@click.option(
    "-a",
    "--agent",
    required=True,
    metavar="<agent>",
    help="Name of the agent whose workspace should be cleaned.",
)
@click.option("-f", "--force", is_flag=True, default=False, help="Skip interactive confirmation.")
@click.option(
    "--all",
    "remove_all",
    is_flag=True,
    default=False,
    help="Remove all directories including staging.",
)
@handles_user_errors("clean")
@requires_project
def clean_cli(agent: str, force: bool, remove_all: bool, project_root: Path | None = None) -> None:
    args = CleanCommandArgs(agent=agent, force=force, all=remove_all)
    Cleaner(
        agent=args.agent, force=args.force, remove_all=args.all, project_root=project_root
    ).run()
