"""Usage command: the tokens each action's model calls used, and what they cost.

    agac usage -a <workflow> [--run <id>] [--json]

Reads the sums the runs of a workflow stored (`llm.providers.usage_tracker`), so it
answers while a run is going on and adds up the runs that submit and collect one batch.
"""

import json
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.renderers.whole_table import print_whole
from agent_actions.config.path_config import load_project_config, resolve_project_root
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.config.prices import ModelPrice, estimated_cost, parse_prices
from agent_actions.llm.providers.usage_tracker import merged, stored_usage, totals
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

Row = dict[str, Any]


def usage_report(entries: list[Row], prices: dict[str, ModelPrice], order: list[str]) -> Row:
    """The stored *entries* summed per action, kind, pricing and model, with a total.

    ``estimated_cost`` is None on a row the price table cannot price. An action's and
    the total's is the sum over the rows it can price, None when it can price none, and
    ``unpriced`` names what the table lacks for the rest.
    """
    rows_of: dict[str, list[Row]] = {}
    for entry in entries:
        rows_of.setdefault(str(entry.get("action")), []).extend(entry["rows"])

    unpriced: set[str] = set()

    def priced(row: Row) -> Row:
        cost, lacking = estimated_cost(prices, row)
        if lacking is not None:
            unpriced.add(lacking)
        return {**row, "estimated_cost": cost}

    def summed(rows: list[Row]) -> Row:
        costs = [row["estimated_cost"] for row in rows if row["estimated_cost"] is not None]
        return {**totals(rows), "estimated_cost": sum(costs) if costs else None}

    names = [name for name in order if name in rows_of]
    names += sorted(name for name in rows_of if name not in names)
    actions = {}
    every_row: list[Row] = []
    for name in names:
        by_kind = [priced(row) for row in merged(rows_of[name])]
        every_row.extend(by_kind)
        actions[name] = {**summed(by_kind), "by_kind": by_kind}

    return {
        "runs": sorted({str(entry.get("run_id")) for entry in entries}),
        "actions": actions,
        "total": summed(every_row),
        "priced": bool(prices),
        "unpriced": sorted(unpriced),
    }


class UsageCommand:
    """Print what the model calls of a workflow's actions used."""

    def __init__(self, agent: str, run: str | None, as_json: bool) -> None:
        self.agent_name = Path(agent).stem
        self.agent = agent
        self.run = run
        self.as_json = as_json
        self.console = Console()

    def execute(self, project_root: Path | None = None) -> Row:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent, auto_create=False, project_root=project_root
        )
        db_path = paths.io_dir / "store" / f"{self.agent_name}.db"
        if not db_path.exists():
            raise click.ClickException(
                f"No store for workflow '{self.agent_name}' at {db_path}. Has it been run?"
            )
        backend = SQLiteBackend.create_readonly(db_path)
        try:
            entries = stored_usage(backend)
            order = json.loads(backend.load_metadata("execution_order") or "[]")
        finally:
            backend.close()

        if self.run is not None:
            known = sorted({str(entry.get("run_id")) for entry in entries})
            entries = [entry for entry in entries if entry.get("run_id") == self.run]
            if not entries:
                raise click.ClickException(
                    f"No usage is recorded for run '{self.run}' of '{self.agent_name}'. "
                    f"Runs with usage: {', '.join(known) or 'none'}"
                )

        project_config = load_project_config(resolve_project_root(project_root))
        prices = parse_prices(project_config.get("prices"))
        report = {"workflow": self.agent_name, **usage_report(entries, prices, order)}
        if self.as_json:
            click.echo(json.dumps(report, indent=2))
        else:
            self._render(report)
        return report

    def _render(self, report: Row) -> None:
        actions: dict[str, Row] = report["actions"]
        if not actions:
            self.console.print(
                f"[dim]No usage is recorded for '{self.agent_name}'. A run records what "
                "its model calls use.[/dim]"
            )
            return

        runs = report["runs"]
        scope = f"run {runs[0]}" if self.run else f"{len(runs)} run{'' if len(runs) == 1 else 's'}"
        table = Table(title=f"Usage: {self.agent_name} ({scope})")
        table.add_column("Action", style="cyan")
        table.add_column("Kind")
        table.add_column("Pricing")
        table.add_column("Model", style="dim")
        table.add_column("Calls", justify="right")
        table.add_column("Input", justify="right")
        table.add_column("Cache read", justify="right")
        table.add_column("Cache write", justify="right")
        table.add_column("Output", justify="right")
        if report["priced"]:
            table.add_column("Est. cost", justify="right")

        def add(labels: tuple[str, str, str, str], usage: Row, rows: list[Row], style: str) -> None:
            cells = [
                f"{usage['calls']:,}",
                f"{usage['input_tokens']:,}",
                f"{usage['cache_read_input_tokens']:,}",
                f"{usage['cache_creation_input_tokens']:,}",
                f"{usage['output_tokens']:,}",
            ]
            if report["priced"]:
                cells.append(_cost_cell(usage["estimated_cost"], rows))
            table.add_row(*labels, *cells, style=style or None)

        every_row = [row for action in actions.values() for row in action["by_kind"]]
        for name, action in actions.items():
            for row in action["by_kind"]:
                pricing = "batch" if row["batch"] else "online"
                add((name, row["kind"], pricing, row["model"]), row, [row], "")
            if len(action["by_kind"]) > 1:
                add((name, "all", "", ""), action, action["by_kind"], "bold")
        table.add_section()
        add(("Total", "", "", ""), report["total"], every_row, "bold")
        print_whole(self.console, table)

        self.console.print(
            "[dim]Input counts the prompt tokens that the provider did not read from its "
            "cache and did not write to its cache. The sum of Input, Cache read and Cache "
            "write is the full prompt. Kind is main for an "
            "action's own call, repair for a call an expect: repair made, and the name of "
            "the side call for any other (judge).[/dim]"
        )
        lacking = ", ".join(report["unpriced"])
        if not report["priced"]:
            self.console.print(
                "No cost is shown: agent_actions.yml has no prices: block. Add one with "
                "the price of one million tokens for each model to get an estimated cost, "
                "for example\n"
                "  prices:\n"
                "    <model>: {input: 1.00, output: 5.00, cache_read: 0.10, cache_write: 1.25, "
                "batch_discount: 0.5}\n"
                f"This report needs: {lacking}",
                highlight=False,
                markup=False,
            )
            return
        self.console.print(
            "[dim]Est. cost is an estimate from the prices: block of agent_actions.yml, "
            "not the provider's bill.[/dim]"
        )
        if lacking:
            self.console.print(
                f"No cost for the calls that need: {lacking}. Such a row shows no cost, and a "
                "sum marked + leaves it out. Add what is named to prices: in agent_actions.yml.",
                style="yellow",
                highlight=False,
                markup=False,
            )


def _cost_cell(cost: float | None, rows: list[Row]) -> str:
    """A cost, marked ``+`` when it is a sum that leaves an unpriced row out."""
    if cost is None:
        return "-"
    partial = any(row["estimated_cost"] is None for row in rows)
    return f"{cost:,.4f}{'+' if partial else ''}"


@click.command()
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "--run",
    default=None,
    help="Show one run only, by its id in artefact/runs.json (every run if omitted).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
@handles_user_errors("usage")
@requires_project
def usage(agent: str, run: str | None, as_json: bool, project_root: Path | None = None) -> None:
    """Show the tokens each action's model calls used, and an estimated cost.

    One row per action, kind of call (main, repair, judge), pricing (online or batch)
    and model, then a total. The cost column appears when agent_actions.yml has a
    prices: block.

    Examples:
        agac usage -a my_workflow
        agac usage -a my_workflow --run run_my_workflow_1a2b3c4d
        agac usage -a my_workflow --json
    """
    UsageCommand(agent, run, as_json).execute(project_root=project_root)
