"""Clean command for the Agent Actions CLI."""

import click

from agent_actions.cli.args import CleanCommandArgs
from agent_actions.cli.cli_decorators import (
    enter_project,
    handles_user_errors,
    workflow_option,
)
from agent_actions.llm.realtime.cleaner import Cleaner

_NO_SCOPE = (
    "Give --target or --all to say what to clean:\n"
    "  --target     Remove agent_io/target/, the generated output.\n"
    "  --all        Remove all agent_io directories, the store and the\n"
    "               sandbox output included, and reclaim the local records\n"
    "               of the workflow's batches.\n"
    "  -f, --force  Do not ask for confirmation."
)


@click.command(
    name="clean",
    help=(
        "Remove a workflow's working directories. --target removes the generated "
        "output under agent_io/target/; --all removes everything including staging, "
        "the durable store and the sandbox output, and reclaims what a provider recorded locally about "
        "this workflow's batches. With neither, nothing is removed."
    ),
)
@workflow_option(
    required=False,
    help="Name of the workflow whose workspace should be cleaned.  [required]",
)
@click.option("-f", "--force", is_flag=True, default=False, help="Skip interactive confirmation.")
@click.option(
    "--target",
    "remove_target",
    is_flag=True,
    default=False,
    help=(
        "Remove the target directory (agent_io/target/ — your generated output). "
        "Confirms unless --force."
    ),
)
@click.option(
    "--all",
    "remove_all",
    is_flag=True,
    default=False,
    help=(
        "Remove all agent_io directories including target, staging, the sandbox "
        "output and any backend-owned store contents, and reclaim what a provider recorded "
        "locally about this workflow's batches — unrecoverable. Confirms "
        "unless --force."
    ),
)
@handles_user_errors("clean")
def clean_cli(agent: str | None, force: bool, remove_target: bool, remove_all: bool) -> None:
    # Checked before the workflow and the project, so a bare `agac clean` lists the choices.
    if not (remove_target or remove_all):
        raise click.UsageError(_NO_SCOPE)
    if agent is None:
        ctx = click.get_current_context()
        param = next(p for p in ctx.command.params if p.name == "agent")
        raise click.MissingParameter(ctx=ctx, param=param)
    project_root = enter_project()
    args = CleanCommandArgs(agent=agent, force=force, target=remove_target, all=remove_all)
    Cleaner(
        agent=args.agent,
        force=args.force,
        remove_target=args.target,
        remove_all=args.all,
        project_root=project_root,
    ).run()
