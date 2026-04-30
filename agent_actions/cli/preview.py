"""Preview command for viewing SQLite storage data."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend


class PreviewCommand:
    def __init__(
        self,
        workflow: str,
        action: str | None = None,
        limit: int = 10,
        offset: int = 0,
        format_type: str = "table",
        stats_only: bool = False,
    ):
        self.workflow = workflow
        self.action = action
        self.limit = limit
        self.offset = offset
        self.format_type = format_type
        self.stats_only = stats_only
        self.workflow_name = Path(workflow).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.workflow_name, self.workflow, auto_create=False, project_root=project_root
        )

        store_dir = paths.io_dir / "store"
        workflow_dir = paths.io_dir.parent

        db_path = store_dir / f"{self.workflow_name}.db"

        if not db_path.exists():
            self.console.print(
                f"[yellow]No SQLite database found at {db_path}[/yellow]\n"
                f"[dim]This workflow may be using JSON file storage, or hasn't been run yet.[/dim]"
            )
            return

        backend = get_storage_backend(
            workflow_path=str(workflow_dir),
            workflow_name=self.workflow_name,
            backend_type="sqlite",
        )

        try:
            if self.stats_only:
                self._show_stats(backend)
            elif self.action:
                self._preview_action(backend)
            else:
                self._list_actions(backend)
        finally:
            backend.close()

    def _show_stats(self, backend) -> None:
        stats = backend.get_storage_stats()

        self.console.print(
            Panel(
                f"[bold]Database:[/bold] {stats['db_path']}\n"
                f"[bold]Size:[/bold] {stats['db_size_human']}\n"
                f"[bold]Source Records:[/bold] {stats['source_count']}\n"
                f"[bold]Target Records:[/bold] {stats['target_count']}",
                title=f"Storage Stats: {self.workflow_name}",
            )
        )

        if stats["nodes"]:
            table = Table(title="Records by Action")
            table.add_column("Action", style="cyan")
            table.add_column("Records", justify="right", style="green")

            for action_name, count in sorted(stats["nodes"].items()):
                table.add_row(action_name, str(count or 0))

            self.console.print(table)

    def _list_actions(self, backend) -> None:
        stats = backend.get_storage_stats()

        if not stats["nodes"]:
            self.console.print("[yellow]No action data found in database.[/yellow]")
            return

        table = Table(title=f"Actions in {self.workflow_name}")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Action", style="cyan")
        table.add_column("Records", justify="right", style="green")
        table.add_column("Files", justify="right")

        for idx, (action_name, count) in enumerate(sorted(stats["nodes"].items()), 1):
            files = backend.list_target_files(action_name)
            table.add_row(str(idx), action_name, str(count or 0), str(len(files)))

        self.console.print(table)
        self.console.print(
            "\n[dim]Use [bold]agac preview -w WORKFLOW -a ACTION[/bold] to view records for a specific action.[/dim]"
        )

    def _preview_action(self, backend) -> None:
        result = backend.preview_target(
            action_name=self.action,
            limit=self.limit,
            offset=self.offset,
        )

        if "error" in result:
            self.console.print(f"[red]{result['error']}[/red]")
            return

        if result["total_count"] == 0:
            self.console.print(f"[yellow]No data found for action '{self.action}'[/yellow]")
            return

        self.console.print(
            Panel(
                f"[bold]Action:[/bold] {result['action_name']}\n"
                f"[bold]Total Records:[/bold] {result['total_count']}\n"
                f"[bold]Showing:[/bold] {self.offset + 1}-{min(self.offset + self.limit, result['total_count'])} of {result['total_count']}\n"
                f"[bold]Files:[/bold] {len(result['files'])}",
                title=f"Preview: {self.action}",
            )
        )

        records = self._unwrap_records(result["records"])

        if self.format_type == "json":
            self._show_json(records)
        elif self.format_type == "raw":
            self._show_raw(records)
        else:
            self._show_table(records)

        if result["total_count"] > self.offset + self.limit:
            remaining = result["total_count"] - (self.offset + self.limit)
            self.console.print(
                f"\n[dim]{remaining} more records. Use [bold]--offset {self.offset + self.limit}[/bold] to see more.[/dim]"
            )

    def _unwrap_records(self, records: list) -> list:
        """Replace namespaced content with the previewed action's fields.

        With the additive model, record["content"] is
        {"action_a": {...}, "action_b": {...}, ...}. When previewing a
        specific action, unwrap so all formats show that action's fields.

        Guard-skipped actions have ``content[action] = None`` and carry
        ``_state: "guard_skipped"``. Content is set to ``{}`` so json/raw
        formats show the real record structure (empty content + framework
        fields) rather than an invented sentinel.
        """
        if not self.action:
            return records
        out = []
        for record in records:
            if not isinstance(record, dict):
                out.append(record)
                continue
            content = record.get("content")
            if not isinstance(content, dict) or self.action not in content:
                out.append(record)
                continue
            action_ns = content[self.action]
            if action_ns is None:
                out.append({**record, "content": {}})
            elif isinstance(action_ns, dict):
                out.append({**record, "content": action_ns})
            else:
                out.append(record)
        return out

    def _show_table(self, records: list) -> None:
        if not records:
            return

        all_keys: set[str] = set()
        for record in records:
            if isinstance(record, dict) and record.get("_state") not in (
                "cascade_skipped",
                "failed",
                "exhausted",
                "guard_skipped",
                "guard_deferred",
                "guard_filtered",
            ):
                if "content" in record and isinstance(record["content"], dict):
                    all_keys.update(record["content"].keys())
                else:
                    all_keys.update(record.keys())

        display_keys = [k for k in sorted(all_keys) if not k.startswith("_")]

        if len(display_keys) > 6:
            display_keys = display_keys[:6]
            self.console.print(
                "[dim]Showing first 6 columns. Use --format json to see all fields.[/dim]\n"
            )

        table = Table(show_lines=True)
        table.add_column("#", style="dim", justify="right")
        for key in display_keys:
            table.add_column(key, overflow="fold", max_width=40)

        for idx, record in enumerate(records, self.offset + 1):
            if isinstance(record, dict):
                state = record.get("_state")
                if state in (
                    "cascade_skipped",
                    "failed",
                    "exhausted",
                    "guard_skipped",
                    "guard_deferred",
                    "guard_filtered",
                ):
                    label = f"[{str(state).replace('_', '-')}]"
                    values = [str(idx), rich_escape(label)]
                    values.extend("" for _ in display_keys[1:])
                    table.add_row(*values)
                    continue
                data = record["content"] if isinstance(record.get("content"), dict) else record
                values = [str(idx)]
                for key in display_keys:
                    val = data.get(key, "")
                    if isinstance(val, dict | list):
                        serialized = json.dumps(val, ensure_ascii=False)
                        val = serialized[:100] + "..." if len(serialized) > 100 else serialized
                    else:
                        val = str(val)[:100] + "..." if len(str(val)) > 100 else str(val)
                    values.append(rich_escape(val))
                table.add_row(*values)
            else:
                table.add_row(str(idx), rich_escape(str(record)[:100]))

        self.console.print(table)

    def _show_json(self, records: list) -> None:
        json_str = json.dumps(records, indent=2, ensure_ascii=False)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def _show_raw(self, records: list) -> None:
        click.echo(json.dumps(records, ensure_ascii=False))


@click.command()
@click.option("-w", "--workflow", required=True, help="Workflow configuration file name")
@click.option(
    "-a", "--action", default=None, help="Action name to preview (lists all if not specified)"
)
@click.option(
    "-n",
    "--limit",
    default=10,
    type=click.IntRange(min=1),
    help="Maximum number of records to show",
)
@click.option("--offset", default=0, type=click.IntRange(min=0), help="Number of records to skip")
@click.option(
    "-f",
    "--format",
    "format_type",
    default="table",
    type=click.Choice(["table", "json", "raw"]),
    help="Output format",
)
@click.option("--stats", is_flag=True, help="Show storage statistics only")
@handles_user_errors("preview")
@requires_project
def preview(
    workflow: str,
    action: str | None,
    limit: int,
    offset: int,
    format_type: str,
    stats: bool,
    project_root: Path | None = None,
) -> None:
    """
    Preview data stored in the SQLite storage backend.

    Examples:

        # List all actions with data
        agac preview -w my_workflow

        # Preview data for a specific action
        agac preview -w my_workflow -a classify_genre

        # Show as JSON
        agac preview -w my_workflow -a classify_genre -f json

        # Show storage stats
        agac preview -w my_workflow --stats

        # Pagination
        agac preview -w my_workflow -a classify_genre -n 20 --offset 10
    """
    command = PreviewCommand(
        workflow=workflow,
        action=action,
        limit=limit,
        offset=offset,
        format_type=format_type,
        stats_only=stats,
    )
    command.execute(project_root=project_root)
