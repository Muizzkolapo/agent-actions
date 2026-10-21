"""Print the prompt traces of an action as plain text."""

import json
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

_SECTIONS = (
    ("PROMPT", "compiled_prompt"),
    ("CONTEXT", "llm_context"),
    ("RESPONSE", "response_text"),
)


def _print_trace(trace: dict) -> None:
    click.echo(
        f"=== {trace['action_name']} record {trace['record_id']}"
        f" attempt {trace['attempt']} ({trace.get('model_vendor') or '-'}"
        f" {trace.get('model_name') or '-'}) ==="
    )
    for title, field in _SECTIONS:
        click.echo(f"--- {title} ---")
        click.echo(trace.get(field) if trace.get(field) is not None else "(none)")
    click.echo()


@click.command()
@click.option("-w", "--workflow", required=True, help="Workflow configuration file name")
@click.option("-a", "--action", required=True, help="Action whose traces to print")
@click.option("--record", "record_id", default=None, help="Only this record's traces")
@click.option("--json", "as_json", is_flag=True, help="Print the traces as a JSON list")
@handles_user_errors("traces")
@requires_project
def traces(
    workflow: str,
    action: str,
    record_id: str | None,
    as_json: bool,
    project_root: Path | None = None,
) -> None:
    """
    Print the prompt, context and response an action's records were run with.

    The store keeps this text compressed, so read it here rather than with sqlite3.

    Examples:

        agac traces -w my_workflow -a summarize

        agac traces -w my_workflow -a summarize --record <record_id>

        agac traces -w my_workflow -a summarize --json
    """
    workflow_name = Path(workflow).stem
    paths = ProjectPathsFactory.create_project_paths(
        workflow_name, workflow, auto_create=False, project_root=project_root
    )
    db_path = paths.io_dir / "store" / f"{workflow_name}.db"
    if not db_path.exists():
        raise click.ClickException(f"No store for workflow '{workflow_name}' at {db_path}")

    backend = SQLiteBackend.create_readonly(db_path)
    try:
        found = backend.get_prompt_traces(action, record_id)
    finally:
        backend.close()

    if not found:
        scope = f" record '{record_id}'" if record_id else ""
        raise click.ClickException(f"No prompt traces for action '{action}'{scope} in {db_path}")

    if as_json:
        click.echo(json.dumps(found, indent=2, ensure_ascii=False))
        return
    for trace in found:
        _print_trace(trace)
