"""Clean command for the Agent Actions CLI."""

from pathlib import Path

import click

from agent_actions.cli.args import CleanCommandArgs
from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm.realtime.cleaner import Cleaner


@click.command(
    name="clean",
    help=(
        "Remove regenerable working directories created by an agent. "
        "By default removes the source directory only; generated output "
        "under agent_io/target/ requires --target, and --all removes "
        "everything including staging and the durable store."
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
    "--target",
    "remove_target",
    is_flag=True,
    default=False,
    help=(
        "Also remove the target directory (agent_io/target/ — your "
        "generated output). Confirms unless --force."
    ),
)
@click.option(
    "--all",
    "remove_all",
    is_flag=True,
    default=False,
    help=(
        "Remove all agent_io directories including target, staging and any "
        "backend-owned store contents — unrecoverable. Confirms unless --force."
    ),
)
@handles_user_errors("clean")
@requires_project
def clean_cli(
    agent: str,
    force: bool,
    remove_target: bool,
    remove_all: bool,
    project_root: Path | None = None,
) -> None:
    args = CleanCommandArgs(agent=agent, force=force, target=remove_target, all=remove_all)
    Cleaner(
        agent=args.agent,
        force=args.force,
        remove_target=args.target,
        remove_all=args.all,
        project_root=project_root,
    ).run()
