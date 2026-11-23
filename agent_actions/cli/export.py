"""Export command: write a workflow's declared outputs to their database tables."""

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import (
    handles_user_errors,
    requires_project,
    workflow_option,
)
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.connections.export import write_outputs
from agent_actions.utils.project_root import find_project_root


@click.command()
@workflow_option()
@click.option("-A", "--action", default=None, help="Write only this action's output")
@handles_user_errors("export")
@requires_project
def export(agent: str, action: str | None, project_root: Path | None = None) -> None:
    """Write the outputs a workflow declares to their database tables.

    Reads what the last run stored and calls no model, so it can be repeated.
    """
    name = Path(agent).stem
    paths = ProjectPathsFactory.create_project_paths(
        name, agent, auto_create=False, project_root=project_root
    )
    loaded = load_workflow(name, paths, project_root, sends_requests=False, read_only=True)
    declared = (loaded.config.manager.user_config or {}).get("outputs")
    if not declared:
        raise click.ClickException(f"Workflow '{name}' declares no outputs")
    root = project_root or find_project_root(str(paths.current_dir)) or paths.current_dir
    written = write_outputs(loaded.storage_backend, declared, root, only_action=action)
    for table, count in written.items():
        click.echo(f"Wrote {count} rows to {table}")
