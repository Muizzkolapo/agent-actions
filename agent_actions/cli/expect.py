"""Expect commands for the Agent Actions CLI.

Surface:

    agac expect list -a <workflow> [--action NAME] [--json]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.inspect_base import render_title_row
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.expectations.report import ActionTally, tally_action
from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.expectations.types import Expectation
from agent_actions.processing.helpers import bypasses_expectations
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.storage import get_storage_backend

_INERT_REASON = (
    "these rules will not run: a tool or HITL action at file granularity is "
    "processed by a strategy that does not evaluate expectations"
)


def _rule_row(expectation: Expectation) -> dict[str, Any]:
    return {
        "id": expectation.resolved_id,
        "type": expectation.type,
        "field": expectation.field,
        "severity": expectation.severity,
        "params": expectation.params,
        "hint": expectation.hint,
    }


class ExpectListCommand:
    """Print the rules each action would run, resolved the way the runner resolves them."""

    def __init__(self, agent: str, action: str | None, as_json: bool) -> None:
        self.agent_name = Path(agent).stem
        self.action_filter = action
        self.as_json = as_json
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> None:
        inspector = WorkflowInspector(self.agent_name, project_root=project_root)
        # The same preflight `agac run` runs: a workflow it refuses is one
        # whose rules would never execute, and the refusal names the correction.
        inspector.validate(verify_keys=False)

        actions = self._actions_to_list(inspector)
        listing = [
            entry
            for entry in (self._resolve(name, inspector.action_configs[name]) for name in actions)
            if entry is not None
        ]

        if self.as_json:
            click.echo(json.dumps({"workflow": self.agent_name, "actions": listing}, indent=2))
        else:
            self._render(listing)

    def _actions_to_list(self, inspector: WorkflowInspector) -> list[str]:
        configured = inspector.action_configs
        if self.action_filter is None:
            return [name for name in inspector.execution_order if name in configured]
        if self.action_filter not in configured:
            raise click.ClickException(
                f"Action '{self.action_filter}' is not in workflow '{self.agent_name}'. "
                f"Actions: {', '.join(sorted(configured))}"
            )
        return [self.action_filter]

    @staticmethod
    def _resolve(name: str, config: dict[str, Any]) -> dict[str, Any] | None:
        """One action's resolved suite, or None when it declares no ``expect:``."""
        service = create_expectation_service_from_config(
            config.get("expect"), action_name=name, agent_config=config
        )
        if service is None:
            return None
        inert = bypasses_expectations(config)
        return {
            "action": name,
            "suite": service.suite.name,
            "repair": service.repair,
            "executes": not inert,
            "inert_because": _INERT_REASON if inert else None,
            "rules": [_rule_row(e) for e in service.suite.expectations],
        }

    def _render(self, listing: list[dict[str, Any]]) -> None:
        self.console.print()
        total = sum(len(entry["rules"]) for entry in listing)
        render_title_row(
            self.console,
            self.agent_name,
            section="expectations",
            right_meta=f"{total} rule{'s' if total != 1 else ''}"
            f" across {len(listing)} action{'s' if len(listing) != 1 else ''}",
        )

        if not listing:
            scope = (
                f"Action '{self.action_filter}'"
                if self.action_filter
                else "No action in this workflow"
            )
            verb = "does not declare" if self.action_filter else "declares"
            self.console.print(f"\n[dim]{scope} {verb} an expect: block.[/dim]")
            return

        for entry in listing:
            table = Table(title=_heading(entry), title_justify="left")
            table.add_column("Rule", style="cyan", overflow="fold")
            table.add_column("Type", overflow="fold")
            table.add_column("Field", style="magenta", overflow="fold")
            table.add_column("Severity", justify="center")
            table.add_column("Params", style="dim", overflow="fold")

            for rule in entry["rules"]:
                table.add_row(
                    Text(rule["id"]),
                    Text(rule["type"]),
                    _field_cell(rule["field"]),
                    _severity_cell(rule["severity"]),
                    _params_cell(rule["params"]),
                )

            self.console.print()
            if table.row_count:
                self.console.print(table)
            else:
                # A rule-free block is still a contract: conform to the schema.
                self.console.print(_heading(entry, suffix="no rules — the schema is the contract"))


def _heading(entry: dict[str, Any], suffix: str | None = None) -> Text:
    heading = Text(entry["action"], style="bold cyan")
    detail = suffix or f"suite {entry['suite']}"
    heading.append(f"  {detail} · repair {entry['repair']}", style="dim")
    if entry.get("inert_because"):
        heading.append(f"\n  ⚠ {entry['inert_because']}", style="yellow")
    return heading


# Every cell below carries user YAML, where a square bracket is ordinary. Text
# renders it verbatim; a markup string would drop whatever parsed as a tag, and
# a listing that quietly omits part of a rule is worse than no listing.
def _field_cell(field: Any) -> Text:
    if field is None:
        return Text("<record>", style="dim")
    if isinstance(field, list):
        return Text(", ".join(str(f) for f in field))
    return Text(str(field))


def _severity_cell(severity: str) -> Text:
    colour = {"error": "red", "warn": "yellow", "info": "blue"}.get(severity, "white")
    return Text(severity, style=colour)


def _params_cell(params: dict[str, Any]) -> Text:
    if not params:
        return Text("—", style="dim")
    return Text(", ".join(f"{key}={value!r}" for key, value in sorted(params.items())))


class ExpectReportCommand:
    """Aggregate the verdicts a run stored, per action and per rule."""

    def __init__(self, agent: str, action: str | None, as_json: bool) -> None:
        self.agent_name = Path(agent).stem
        self.action_filter = action
        self.as_json = as_json
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> list[ActionTally]:
        inspector = WorkflowInspector(self.agent_name, project_root=project_root)
        # Deliberately load() rather than validate(): a report reads what has
        # already run, and a config that no longer passes preflight is a reason
        # to want the report, not a reason to refuse it.
        inspector.load()

        actions = self._actions_to_report(inspector)
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent_name, auto_create=False, project_root=project_root
        )
        # Reading must not write: initializing a backend creates the database and
        # migrates its schema, so a question about a workflow that never ran would
        # leave a store behind.
        store = paths.io_dir / "store" / f"{self.agent_name}.db"
        tallies: list[ActionTally] = []
        if store.exists():
            backend = get_storage_backend(
                workflow_path=str(paths.io_dir.parent), workflow_name=self.agent_name
            )
            backend.initialize()
            try:
                tallies = [
                    t for t in (self._tally(backend, name) for name in actions) if t is not None
                ]
            finally:
                backend.close()

        if self.as_json:
            click.echo(
                json.dumps(
                    {"workflow": self.agent_name, "actions": [_tally_row(t) for t in tallies]},
                    indent=2,
                )
            )
        else:
            self._render(tallies, actions)
        return tallies

    def _actions_to_report(self, inspector: WorkflowInspector) -> list[str]:
        configured = inspector.action_configs
        if self.action_filter is None:
            # execution_order holds only operational actions. A report reads what
            # already ran, so disabling an action must not hide the verdicts it
            # already wrote.
            ordered = [name for name in inspector.execution_order if name in configured]
            return list(dict.fromkeys(ordered + list(configured)))
        if self.action_filter not in configured:
            raise click.ClickException(
                f"Action '{self.action_filter}' is not in workflow '{self.agent_name}'. "
                f"Actions: {', '.join(sorted(configured))}"
            )
        return [self.action_filter]

    @staticmethod
    def _tally(backend: Any, action: str) -> ActionTally | None:
        records: list[dict[str, Any]] = []
        for relative_path in backend.list_target_files(action):
            records.extend(backend.read_target(action, relative_path))
        return tally_action(action, records)

    def _render(self, tallies: list[ActionTally], asked_for: list[str]) -> None:
        self.console.print()
        records = sum(t.records for t in tallies)
        render_title_row(
            self.console,
            self.agent_name,
            section="expectation verdicts",
            right_meta=f"{records} record{'s' if records != 1 else ''}"
            f" across {len(tallies)} action{'s' if len(tallies) != 1 else ''}",
        )

        if not tallies:
            named = ", ".join(asked_for) if len(asked_for) <= 4 else f"{len(asked_for)} actions"
            self.console.print(
                f"\n[dim]No stored verdict for {named}. "
                f"Expectations are written by a run; run the workflow first.[/dim]"
            )
            return

        for tally in tallies:
            self.console.print()
            if not tally.rules:
                # A rule-free expect: block still gates on the schema, so its
                # records have a verdict but nothing per-rule to tabulate.
                self.console.print(
                    _report_heading(tally, suffix="no rules — the schema is the contract")
                )
                continue

            table = Table(title=_report_heading(tally), title_justify="left")
            table.add_column("Rule", style="cyan")
            table.add_column("Type")
            table.add_column("Severity", justify="center")
            table.add_column("Passed", justify="right", style="green")
            table.add_column("Failed", justify="right", style="red")
            table.add_column("Skipped", justify="right", style="yellow")
            table.add_column("Pass rate", justify="right")

            for rule in tally.rules:
                table.add_row(
                    Text(rule.id),
                    Text(rule.type),
                    _severity_cell(rule.severity),
                    Text(str(rule.passed)),
                    Text(str(rule.failed)),
                    Text(str(rule.skipped)),
                    Text(_rate(rule.pass_rate)),
                )

            self.console.print(table)


def _rate(value: float | None) -> str:
    """A rate that never renders an imperfect result as a perfect one."""
    if value is None:
        return "—"
    percent = value * 100
    if percent not in (0.0, 100.0) and round(percent) in (0, 100):
        return f"{percent:.1f}%"
    return f"{percent:.0f}%"


def _report_heading(tally: ActionTally, suffix: str | None = None) -> Text:
    heading = Text(tally.action, style="bold cyan")
    detail = f"{tally.records_passed}/{tally.records} records passed · {_rate(tally.pass_rate)}"
    if suffix:
        detail = f"{detail} · {suffix}"
    heading.append(f"  {detail}", style="dim")
    if tally.unverified:
        # The rate above is over rated records only; without this the survivors
        # of a run that tombstoned records would read as full health.
        heading.append(
            f"  ⚠ {tally.unverified} record{'s' if tally.unverified != 1 else ''} carried no verdict",
            style="yellow",
        )
    return heading


def _tally_row(tally: ActionTally) -> dict[str, Any]:
    return {
        "action": tally.action,
        "records": tally.records,
        "records_passed": tally.records_passed,
        "records_total": tally.records_total,
        "unverified": tally.unverified,
        "pass_rate": tally.pass_rate,
        "rules": [
            {
                "id": rule.id,
                "type": rule.type,
                "severity": rule.severity,
                "passed": rule.passed,
                "failed": rule.failed,
                "skipped": rule.skipped,
                "pass_rate": rule.pass_rate,
            }
            for rule in tally.rules
        ],
    }


@click.group(invoke_without_command=False)
def expect() -> None:
    """Inspect expectation rules and verdicts.

    \b
    Examples:
        agac expect list -a my_workflow
        agac expect list -a my_workflow --action extract_facts
        agac expect list -a my_workflow --json
        agac expect report -a my_workflow
    """


@expect.command("list")
@click.option("-a", "--agent", "agent_opt", required=True, help="Workflow name.")
@click.option("--action", default=None, help="Limit the listing to one action.")
@click.option("--json", "as_json", is_flag=True, help="Emit the listing as JSON.")
@handles_user_errors("expect list")
@requires_project
def list_rules(
    agent_opt: str,
    action: str | None,
    as_json: bool,
    project_root: Path | None = None,
) -> None:
    """List the expectation rules each action would run.

    Rules are resolved through the same loader the runner uses, so an inline
    expectations: list, a named suite:, and a bare expect: reading the action's
    own schema all print what would actually execute.
    """
    ExpectListCommand(agent=agent_opt, action=action, as_json=as_json).execute(
        project_root=project_root
    )


@expect.command("report")
@click.option("-a", "--agent", "agent_opt", required=True, help="Workflow name.")
@click.option("--action", default=None, help="Limit the report to one action.")
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
@requires_project
@handles_user_errors("expect report")
def report(
    agent_opt: str,
    action: str | None,
    as_json: bool,
    project_root: Path | None = None,
) -> None:
    """Report the expectation verdicts a run stored.

    Rules are ordered by how often they failed, so the rule costing the most
    records is the first one listed for its action.
    """
    ExpectReportCommand(agent=agent_opt, action=action, as_json=as_json).execute(
        project_root=project_root
    )


__all__ = ["expect", "ExpectListCommand", "ExpectReportCommand"]
