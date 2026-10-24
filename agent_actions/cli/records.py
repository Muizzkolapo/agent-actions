"""Print an action's stored records, or failed records' inputs, as JSON."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

_PAGE = 1000


def _field(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _stored_records(
    backend: SQLiteBackend, action: str, relative_path: str | None
) -> Iterator[dict[str, Any]]:
    """Every record an action stores, as ``agac preview`` shows them, file by file."""
    offset = 0
    while True:
        page = backend.preview_target(
            action, limit=_PAGE, offset=offset, relative_path=relative_path
        )
        if page.get("error"):
            raise click.ClickException(page["error"])
        if not page["records"]:
            return
        for record in page["records"]:
            yield {"_action": action, **record}
        offset += len(page["records"])


def _snapshots(backend: SQLiteBackend, actions: list[str]) -> list[dict[str, Any]]:
    """The input each failed or exhausted record was processed with, parsed."""
    found = []
    for action in actions:
        for row in backend.get_disposition(action):
            snapshot = row.get("input_snapshot")
            if snapshot is None:
                continue
            try:
                parsed: Any = json.loads(snapshot)
            except ValueError:
                parsed = snapshot
            found.append(
                {
                    "_action": action,
                    "record_id": row["record_id"],
                    "disposition": row["disposition"],
                    "reason": row.get("reason"),
                    "relative_path": row.get("relative_path"),
                    "input_snapshot": parsed,
                }
            )
    return found


@click.command()
@click.option("-w", "--workflow", required=True, help="Workflow configuration file name")
@click.option(
    "-a", "--action", default=None, help="Only this action's records (every action if omitted)"
)
@click.option("--source-guid", default=None, help="Only the records of this source record")
@click.option("--file", "relative_path", default=None, help="Only the records of this stored file")
@click.option(
    "--field",
    default=None,
    help="Print one value per record: a dotted path into it, such as content.summary",
)
@click.option(
    "--snapshots",
    is_flag=True,
    help="Print the input each failed or exhausted record was processed with instead",
)
@handles_user_errors("records")
@requires_project
def records(
    workflow: str,
    action: str | None,
    source_guid: str | None,
    relative_path: str | None,
    field: str | None,
    snapshots: bool,
    project_root: Path | None = None,
) -> None:
    """Print the records an action stored, as a JSON list.

    The store keeps them compressed, so read them here rather than with sqlite3. Each
    record carries ``_action`` and ``_file``; ``--snapshots`` prints the input each
    failed or exhausted record was processed with.
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
        if snapshots:
            actions = [action] if action else backend.actions_with_dispositions()
            found = _snapshots(backend, actions)
            if source_guid:
                found = [row for row in found if row["record_id"] == source_guid]
            if relative_path:
                found = [row for row in found if row["relative_path"] == relative_path]
        else:
            actions = [action] if action else sorted(backend.get_storage_stats()["nodes"])
            if action and not backend.list_target_files(action):
                raise click.ClickException(f"No stored records for action '{action}' in {db_path}")
            if relative_path and not action:
                # Across every action, a file is read where it is stored and skipped elsewhere.
                actions = [
                    name for name in actions if relative_path in backend.list_target_files(name)
                ]
            found = [
                record
                for name in actions
                for record in _stored_records(backend, name, relative_path)
                if source_guid is None or record.get("source_guid") == source_guid
            ]
    finally:
        backend.close()

    if field is not None:
        shown: list[Any] = [_field(record, field) for record in found]
    else:
        shown = found
    click.echo(json.dumps(shown, indent=2, ensure_ascii=False, default=str))
