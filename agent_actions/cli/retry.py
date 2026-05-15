"""Retry command for the Agent Actions CLI.

Retries failed/exhausted records from a specific action forward.
Uses the disposition table to identify what failed and delegates to
the existing workflow execution engine for re-processing.
"""

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import DISPOSITION_EXHAUSTED, DISPOSITION_FAILED
from agent_actions.validation.retry_validator import RetryCommandArgs

logger = logging.getLogger(__name__)

_FAILURE_DISPOSITIONS = (DISPOSITION_FAILED, DISPOSITION_EXHAUSTED)


class RetryCommand:
    """Retry failed/exhausted records from a given action forward."""

    def __init__(self, args: RetryCommandArgs):
        self.args = args
        self.agent_name = Path(args.agent).stem
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.args.agent, auto_create=False, project_root=project_root
        )

        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent),
            workflow_name=self.agent_name,
        )

        workflow = load_workflow(self.agent_name, paths, project_root)
        execution_order = list(workflow.execution_order)

        failures = self._find_failures(backend, execution_order)

        if not failures:
            self.console.print(
                "[green]No failed or exhausted records found. Nothing to retry.[/green]"
            )
            return

        from_action = self.args.from_action
        if from_action:
            if from_action not in execution_order:
                raise click.ClickException(
                    f"Action '{from_action}' not found in execution order: {execution_order}"
                )
        else:
            for action in execution_order:
                if action in failures:
                    from_action = action
                    break

        if not from_action:
            self.console.print("[green]No actionable failures found.[/green]")
            return

        target_records = failures.get(from_action, [])
        if self.args.record:
            target_records = [r for r in target_records if r["record_id"] == self.args.record]
            if not target_records:
                raise click.ClickException(
                    f"Record '{self.args.record}' not found in failed records "
                    f"for action '{from_action}'"
                )

        self._display_retry_plan(from_action, target_records, execution_order)

        if self.args.dry_run:
            self.console.print("\n[yellow]Dry run — no changes made.[/yellow]")
            return

        from_idx = execution_order.index(from_action)
        downstream_actions = execution_order[from_idx:]
        record_ids = {r["record_id"] for r in target_records}

        logger.warning(
            "Clearing dispositions for retry: records=%s, actions=%s. "
            "If the re-run fails, run 'retry' again to resume.",
            sorted(record_ids),
            downstream_actions,
        )

        cleared = 0
        for action in downstream_actions:
            for record_id in record_ids:
                cleared += backend.clear_disposition(action, record_id=record_id)

        self.console.print(
            f"\n[cyan]Cleared {cleared} disposition(s) for {len(record_ids)} record(s) "
            f"across {len(downstream_actions)} action(s).[/cyan]"
        )

        self.console.print("\n[bold]Re-running workflow...[/bold]\n")
        workflow = load_workflow(self.agent_name, paths, project_root)
        workflow.run()
        self.console.print("\n[green]Retry complete.[/green]")

    @staticmethod
    def _find_failures(
        backend,
        execution_order: list[str],
    ) -> dict[str, list[dict]]:
        """Query disposition table for failed/exhausted records per action."""
        failures: dict[str, list[dict]] = {}
        for action in execution_order:
            rows = backend.get_disposition(action)
            action_failures = [r for r in rows if r.get("disposition") in _FAILURE_DISPOSITIONS]
            if action_failures:
                failures[action] = action_failures
        return failures

    def _display_retry_plan(
        self,
        from_action: str,
        target_records: list[dict],
        execution_order: list[str],
    ) -> None:
        """Display what will be retried."""
        from_idx = execution_order.index(from_action)
        downstream = execution_order[from_idx:]

        self.console.print("\n[bold]Retry Plan[/bold]")
        self.console.print(f"  From action: [cyan]{from_action}[/cyan]")
        self.console.print(f"  Actions to re-run: {' → '.join(downstream)}")
        self.console.print(f"  Records to retry: {len(target_records)}")

        table = Table(title="Failed Records")
        table.add_column("Record ID", style="red")
        table.add_column("Disposition", style="yellow")
        table.add_column("Reason", style="dim", max_width=60)

        for record in target_records:
            table.add_row(
                record.get("record_id", "?"),
                record.get("disposition", "?"),
                (record.get("reason") or "")[:60],
            )

        self.console.print(table)


@click.command()
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "--from",
    "from_action",
    default=None,
    help="Action to retry from. If omitted, retries from earliest failure.",
)
@click.option(
    "--record",
    default=None,
    help="Specific record source_guid to retry.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be retried without executing.",
)
@handles_user_errors("retry")
@requires_project
def retry(
    agent: str,
    from_action: str | None,
    record: str | None,
    dry_run: bool,
    project_root: Path | None = None,
) -> None:
    """Retry failed/exhausted records from a specific action forward."""
    args = RetryCommandArgs(
        agent=agent,
        from_action=from_action,
        record=record,
        dry_run=dry_run,
    )
    command = RetryCommand(args)
    command.execute(project_root=project_root)
