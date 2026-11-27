"""Inspect commands for the Agent Actions CLI.

Surface:

    agac inspect -a <workflow>                 # validated action list
    agac inspect action  -a <workflow> ACTION  # action drill-down
    agac inspect context -a <workflow> ACTION  # template variables
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
from rich.markup import escape

from agent_actions.cli.cli_decorators import (
    _format_project_root_display,
    handles_user_errors,
    sandbox_option,
    scenario_option,
    workflow_option,
)
from agent_actions.cli.inspect_base import branch_of, render_title_row
from agent_actions.config.loops import is_loop_pick, loop_of
from agent_actions.llm.providers.tools.builtin import PICK, RETRIEVE, ROUTE, builtin_tool
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.project_root import ensure_in_project

from .inspect_action import ActionCommand, ContextCommand, action, context
from .inspect_base import BaseInspectCommand


class InspectCommand(BaseInspectCommand):
    """Default ``agac inspect`` — one ✓ per action, one ✅ badge for the workflow."""

    def execute(self, project_root: Path | None = None) -> None:
        inspector = self._load_inspector(project_root=project_root)
        self._render_action_list(inspector)

    def _render_action_list(self, inspector: WorkflowInspector) -> None:
        # `get_levels()` includes non-operational actions that ConfigManager
        # filters out of `execution_order`. Sort within each level so
        # version siblings render `foo_1, foo_2, foo_3` (runtime order is reversed).
        order = [
            name
            for level in inspector.get_levels()
            for name in sorted(level)
            if not _in_loop(inspector.action_configs.get(name, {}))
        ]
        n = len(order)

        self.console.print()
        render_title_row(
            self.console,
            self.agent_name,
            validated=True,
            right_meta=f"{n} action{'s' if n != 1 else ''}",
        )
        self.console.print()

        width = max((len(name) for name in order), default=0)
        for name in order:
            note = _note(inspector.action_configs.get(name, {}))
            if note is None:
                self.console.print(f"  [green]✓[/green]  {name}", highlight=False)
            else:
                self.console.print(
                    f"  [green]✓[/green]  {name.ljust(width)}  [dim]{escape(note)}[/dim]",
                    highlight=False,
                )


def _in_loop(config: dict[str, Any]) -> bool:
    """Whether *config* is an action of one iteration of a loop, shown as the loop."""
    return loop_of(config) is not None and not is_loop_pick(config)


def _note(config: dict[str, Any]) -> str | None:
    """What an action is beyond its name: its branch, or the entry it was written as."""
    spec = builtin_tool(config)
    loop = loop_of(config) if is_loop_pick(config) else None
    if loop is not None:
        return (
            f"loop ×{loop['max_iterations']} max, until {loop['until']} "
            f"(branch {loop['branch']}, result {loop['result']})"
        )
    if spec is not None and spec["tool"] == ROUTE:
        cases = " · ".join(
            f"{case} → {members if isinstance(members, str) else ', '.join(members)}"
            for case, members in spec.get("branches", {}).items()
        )
        return f"route on {spec['field']}: {cases}"
    if spec is not None and spec["tool"] == PICK:
        return f"join of {', '.join(spec['of'])}"
    if spec is not None and spec["tool"] == RETRIEVE:
        return (
            f"{spec['action']}: retrieve '{spec['entry']}' from knowledge base {spec['base']} "
            f"by {', '.join(spec['methods'])} on {', '.join(spec['query'])}, "
            f"top {spec['top_k']}"
        )
    branch = branch_of(config)
    if branch is None:
        return None
    named = f" as {branch['instance']}" if "instance" in branch else ""
    return f"from branch {branch['name']}{named}"


@click.group(name="inspect", invoke_without_command=True)
@workflow_option("agent_opt", required=False)
@sandbox_option(
    help="Show the workflow as agac run --sandbox runs it: each LLM action on the offline mock",
    note="each LLM action is shown as the offline mock answers it",
)
@scenario_option()
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.pass_context
@handles_user_errors("inspect")
def inspect(
    ctx: click.Context,
    agent_opt: str | None,
    user_code: str | None,
) -> None:
    """Inspect workflow structure and validation status.

    Default: one ✓ per action, one ✅ badge for the whole workflow.
    Reaching the list at all means preflight passed — malformed schemas,
    dangling refs, invalid guards etc. fail before the list renders.

    \b
    Examples:
        agac inspect -a my_workflow
        agac inspect action  -a my_workflow extract_facts
        agac inspect context -a my_workflow extract_facts
    """
    # Forward group-level `-a` / `-u` to the invoked subcommand so
    # `agac inspect -a foo action <name>` works.
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
            "Missing required option '-w' / '--workflow'. Run 'agac inspect --help' for usage."
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
