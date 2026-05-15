"""Dispositions command — inspect record-level processing outcomes per action.

Shows per-action breakdown of record dispositions (success, failed,
exhausted, quarantined, etc.) to help diagnose workflow issues and
identify records that need retry.
"""

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID

logger = logging.getLogger(__name__)


class DispositionsCommand:
    """Display per-action disposition breakdown for a workflow."""

    def __init__(self, agent: str, action: str | None, quarantined: bool):
        self.agent_name = Path(agent).stem
        self.agent = agent
        self.action_filter = action
        self.quarantined_only = quarantined
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent, auto_create=False, project_root=project_root
        )

        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent),
            workflow_name=self.agent_name,
        )

        execution_order = self._load_execution_order(paths, project_root)

        if self.action_filter:
            if self.action_filter not in execution_order:
                raise click.ClickException(
                    f"Action '{self.action_filter}' not in execution order: {execution_order}"
                )
            actions = [self.action_filter]
        else:
            actions = execution_order

        if self.quarantined_only:
            self._show_quarantined(backend, actions)
        else:
            self._show_summary(backend, actions)

    def _show_summary(self, backend, actions: list[str]) -> None:
        """Show per-action disposition counts."""
        table = Table(title=f"Dispositions: {self.agent_name}")
        table.add_column("Action", style="cyan")
        table.add_column("Success", justify="right", style="green")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Exhausted", justify="right", style="red")
        table.add_column("Quarantined", justify="right", style="yellow")
        table.add_column("Passthrough", justify="right", style="dim")
        table.add_column("Filtered", justify="right", style="dim")
        table.add_column("Total", justify="right", style="bold")

        for action in actions:
            rows = backend.get_disposition(action)
            # Exclude node-level sentinel records
            rows = [r for r in rows if r.get("record_id") != NODE_LEVEL_RECORD_ID]

            counts: dict[str, int] = {}
            for row in rows:
                disp = row.get("disposition", "unknown")
                counts[disp] = counts.get(disp, 0) + 1

            total = sum(counts.values())
            if total == 0:
                continue

            table.add_row(
                action,
                str(counts.get("success", 0)),
                str(counts.get("failed", 0)),
                str(counts.get("exhausted", 0)),
                str(counts.get("unprocessed", 0)),
                str(counts.get("passthrough", 0)),
                str(counts.get("filtered", 0)),
                str(total),
            )

        self.console.print(table)

    def _show_quarantined(self, backend, actions: list[str]) -> None:
        """Show details of failed/exhausted/unprocessed records."""
        table = Table(title=f"Quarantined Records: {self.agent_name}")
        table.add_column("Action", style="cyan")
        table.add_column("Record ID", style="red")
        table.add_column("Disposition", style="yellow")
        table.add_column("Reason", style="dim", max_width=60)

        found = 0
        for action in actions:
            for disp in ("failed", "exhausted", "unprocessed"):
                rows = backend.get_disposition(action, disposition=disp)
                rows = [r for r in rows if r.get("record_id") != NODE_LEVEL_RECORD_ID]
                for row in rows:
                    found += 1
                    table.add_row(
                        action,
                        row.get("record_id", "?"),
                        row.get("disposition", "?"),
                        (row.get("reason") or "")[:60],
                    )

        if found:
            self.console.print(table)
        else:
            self.console.print("[green]No quarantined records found.[/green]")

    def _load_execution_order(self, paths, project_root: Path | None) -> list[str]:
        """Load the workflow to extract execution order."""
        from agent_actions.config.loader import find_config_file
        from agent_actions.config.rendering import ConfigRenderingService
        from agent_actions.workflow.coordinator import AgentWorkflow
        from agent_actions.workflow.runtime_config import WorkflowPaths, WorkflowRuntimeConfig

        filename = f"{self.agent_name}.yml"
        full_path = find_config_file(
            self.agent_name,
            paths.agent_config_dir,
            filename,
            check_alternatives=True,
            project_root=project_root,
        )
        ConfigRenderingService().render_and_load_config(
            self.agent_name,
            full_path,
            paths.template_dir,
            paths.rendered_workflows_dir,
            project_root=project_root,
        )
        workflow = AgentWorkflow(
            WorkflowRuntimeConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    default_path=str(paths.default_config_path),
                ),
                project_root=project_root,
            )
        )
        return list(workflow.execution_order)


@click.command()
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "--action",
    default=None,
    help="Show dispositions for a specific action only.",
)
@click.option(
    "--quarantined",
    is_flag=True,
    default=False,
    help="Show only failed/exhausted/unprocessed records with details.",
)
@handles_user_errors("dispositions")
@requires_project
def dispositions(
    agent: str,
    action: str | None,
    quarantined: bool,
    project_root: Path | None = None,
) -> None:
    """Inspect record-level processing dispositions per action."""
    command = DispositionsCommand(agent, action, quarantined)
    command.execute(project_root=project_root)
