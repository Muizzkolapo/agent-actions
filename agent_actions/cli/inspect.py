"""Inspect commands for the Agent Actions CLI.

Surface:

    agac inspect -a <workflow>                 # graph + validation
    agac inspect action  -a <workflow> ACTION  # action drill-down
    agac inspect context -a <workflow> ACTION  # template variables
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_actions.cli.cli_decorators import _format_project_root_display, handles_user_errors
from agent_actions.cli.inspect_base import (
    collapse_version_groups,
    compute_graph_hash,
    render_title_row,
)
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.project_root import ensure_in_project

from .inspect_action import ActionCommand, ContextCommand, action, context
from .inspect_base import BaseInspectCommand


class InspectCommand(BaseInspectCommand):
    """Default ``agac inspect`` — stat cards + dependency graph + validation."""

    def execute(self, project_root: Path | None = None) -> None:
        inspector = self._load_inspector(project_root=project_root)
        self._output_graph_with_validation(inspector)

    def _output_graph_with_validation(self, inspector: WorkflowInspector) -> None:
        levels = inspector.get_levels()
        estimate = inspector.estimate()
        steps = self._build_steps(levels)
        graph_hash = compute_graph_hash(inspector.action_configs)
        # Cache for `_collapse_version_groups` — it needs to read
        # `is_versioned_agent` to avoid folding unrelated `step_1`/`step_2`
        # names into one pill.
        self._inspector_action_configs = inspector.action_configs

        self.console.print()
        render_title_row(self.console, self.agent_name, validated=True, graph_hash=graph_hash)
        self.console.print()

        # Stat cards row — 4 equal-width cards in a borderless grid.
        # Columns(equal=True) gives ragged inter-card gaps because Rich
        # left-aligns each card and distributes leftover columns
        # unevenly; Table.grid with 4 ratio-1 columns sits flush.
        stats = Table.grid(expand=True, padding=(0, 1))
        for _ in range(4):
            stats.add_column(ratio=1, justify="left")
        stats.add_row(
            self._stat_card(str(estimate["action_count"]), "ACTIONS", "bold cyan"),
            self._stat_card(str(len(levels)), "LEVELS", "bold bright_white"),
            self._stat_card(str(estimate["llm_calls"]), "LLM CALLS", "bold yellow"),
            self._stat_card(str(estimate["guarded_actions"]), "GUARDED", "bold bright_red"),
        )
        self.console.print(stats)
        self.console.print()

        # Section divider — left + right labels with rule line between.
        # Rich Rule's title centres in fixed space, so build the line
        # by hand: dim label · padded rule · dim label.
        width = self.console.width or 100
        left_label = "DEPENDENCY GRAPH"
        right_label = "TOP-DOWN EXECUTION"
        rule_chars = max(width - len(left_label) - len(right_label) - 4, 8)
        rule = Text()
        rule.append(left_label + " ", style="dim")
        rule.append("─" * rule_chars, style="dim rgb(70,80,95)")
        rule.append(" " + right_label, style="dim")
        self.console.print(rule)
        self.console.print()

        # Step rows: numbered by ACTION POSITION (matches the mockup —
        # `03-05` means the 3rd through 5th actions in the workflow).
        # Walk steps tracking running position.
        position = 1
        for step in steps:
            count = len(step["actions"])
            self._render_step(position, position + count - 1, step)
            position += count
            self.console.print()

    # ── Header helpers ────────────────────────────────────────────────

    @staticmethod
    def _stat_card(value: str, label: str, value_style: str):
        number = Text(value, style=value_style, justify="left")
        sub = Text(label, style="dim", justify="left")
        return Panel(Group(number, sub), border_style="rgb(60,75,90)", padding=(1, 2))

    # ── Step rendering (cards / pills / chains) ──────────────────────

    def _render_step(self, start: int, end: int, step: dict[str, object]) -> None:
        gutter = self._step_gutter(start, end)

        if step["kind"] == "parallel":
            collapsed = self._collapse_version_groups(step["actions"])
            header = Text(
                f"⫻ FAN-OUT · {len(step['actions'])} PARALLEL CALLS",
                style="bold yellow",
            )
            # Pills wrap at pill boundaries — Rich's default word-wrap
            # would split mid-name and leave half-coloured chips.
            body_width = max((self.console.width or 100) - 14, 30)
            pill_rows = self._parallel_pill_rows(collapsed, body_width)
            body = Panel(
                Group(header, Text(""), *pill_rows),
                border_style="rgb(60,120,100)",
                padding=(0, 1),
                expand=False,
            )
        else:
            body = self._chain_pills(step["actions"])

        self.console.print(self._row(gutter, body))

    @staticmethod
    def _step_gutter(start: int, end: int) -> Text:
        label_text = f"{start:02d}" if start == end else f"{start:02d}-{end:02d}"
        text = Text()
        text.append(f"{label_text:<6}", style="dim")
        text.append("●", style="bold rgb(108,168,138)")
        text.append("─ ", style="dim rgb(108,168,138)")
        return text

    @staticmethod
    def _action_pill(name: str) -> Text:
        pill = Text()
        pill.append(" ● ", style="rgb(108,168,138) on rgb(28,52,46)")
        pill.append(f"{name} ", style="bold rgb(180,220,200) on rgb(28,52,46)")
        return pill

    def _parallel_pill_rows(self, actions: list[str], max_width: int) -> list[Text]:
        rows: list[Text] = []
        current = Text()
        for name in actions:
            pill_cell_len = len(name) + 4  # ` ● name `
            sep_cell_len = 3 if current.cell_len else 0
            # Wrap when adding this pill would overflow — including the
            # single-pill case where `current` is empty (a very long
            # pill on a narrow terminal still needs its own row, not
            # silent overflow of the panel border).
            if current.cell_len and current.cell_len + sep_cell_len + pill_cell_len > max_width:
                rows.append(current)
                current = Text()
            elif current.cell_len:
                current.append("   ")
            current.append_text(self._action_pill(name))
        if current.cell_len:
            rows.append(current)
        return rows

    def _chain_pills(self, actions: list[str]) -> Group:
        """Wrap chain pills at pill boundaries — Rich's word-wrap
        otherwise splits mid-name and leaves half-coloured chips."""
        # Terminal width minus the left gutter (8 chars).
        body_width = max((self.console.width or 100) - 10, 40)

        lines: list[Text] = []
        current = Text()
        for i, name in enumerate(actions):
            # Each pill takes len(name) + 4 cells (` ● name `).
            pill_len = len(name) + 4
            sep_len = 5 if i > 0 else 0  # `  →  `
            if i > 0 and current.cell_len + sep_len + pill_len > body_width:
                lines.append(current)
                current = Text()
                # Indent continuation pills with arrow at start so the
                # chain signal carries across lines.
                current.append("→  ", style="dim")
            elif i > 0:
                current.append("  ")
                current.append("→", style="dim")
                current.append("  ")
            current.append_text(self._action_pill(name))
        if current.cell_len:
            lines.append(current)
        return Group(*lines)

    @staticmethod
    def _row(left, right):
        """Place `left` and `right` on one row using a 2-col table.

        Rich `Columns` doesn't align baselines for mixed Text + Panel,
        so use a Table with no borders and `vertical='middle'`.
        """

        table = Table.grid(padding=(0, 0))
        table.add_column(no_wrap=True, vertical="top")
        table.add_column()
        table.add_row(left, right)
        return table

    @staticmethod
    def _build_steps(levels: list[list[str]]) -> list[dict[str, object]]:
        """Group consecutive single-action levels into one "serial" step,
        keep multi-action levels as standalone "parallel" steps.
        """
        steps: list[dict[str, object]] = []
        idx = 0
        while idx < len(levels):
            level = levels[idx]
            if len(level) > 1:
                steps.append({"kind": "parallel", "actions": list(level)})
                idx += 1
                continue
            chain = [level[0]]
            while idx + 1 < len(levels) and len(levels[idx + 1]) == 1:
                idx += 1
                chain.append(levels[idx][0])
            steps.append({"kind": "serial", "actions": chain})
            idx += 1
        return steps

    def _collapse_version_groups(self, actions: list[str]) -> list[str]:
        configs = getattr(self, "_inspector_action_configs", None) or {}
        return collapse_version_groups(actions, configs)


@click.group(name="inspect", invoke_without_command=True)
@click.option("-a", "--agent", "agent_opt", required=False, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.pass_context
@handles_user_errors("inspect")
def inspect(
    ctx: click.Context,
    agent_opt: str | None,
    user_code: str | None,
) -> None:
    """Inspect workflow structure and validation status.

    Default: dependency graph with validation status.

    \b
    Examples:
        agac inspect -a my_workflow
        agac inspect action  -a my_workflow extract_facts
        agac inspect context -a my_workflow extract_facts
    """
    # ``default_map`` forwards group-level ``-a`` / ``-u`` to the
    # subcommand so ``agac inspect -a foo action <name>`` works (subcommands
    # still mark ``-a`` required, so missing-option errors fire as before).
    if ctx.invoked_subcommand is not None:
        defaults: dict[str, str] = {}
        if agent_opt:
            defaults["agent"] = agent_opt
        if user_code:
            defaults["user_code"] = user_code
        if defaults:
            existing = ctx.default_map or {}
            ctx.default_map = {
                **existing,
                ctx.invoked_subcommand: {
                    **(existing.get(ctx.invoked_subcommand) or {}),
                    **defaults,
                },
            }
        return

    if not agent_opt:
        raise click.UsageError(
            "Missing required option '-a' / '--agent'. Run 'agac inspect --help' for usage."
        )

    project_root = ensure_in_project()
    display = _format_project_root_display(project_root)
    if display != ".":
        click.echo(f"\U0001f4c1 Project root: {display}", err=True)
    InspectCommand(agent=agent_opt, user_code=user_code).execute(project_root=project_root)


inspect.add_command(action)
inspect.add_command(context)

__all__ = [
    "inspect",
    "BaseInspectCommand",
    "ActionCommand",
    "ContextCommand",
    "InspectCommand",
]
