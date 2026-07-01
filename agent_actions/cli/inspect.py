"""Inspect commands for the Agent Actions CLI.

Surface:

    agac inspect -a <workflow>                 # validated action list
    agac inspect action  -a <workflow> ACTION  # action drill-down
    agac inspect context -a <workflow> ACTION  # template variables
"""

from __future__ import annotations

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import _format_project_root_display, handles_user_errors
from agent_actions.cli.inspect_base import render_title_row
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
        order = [name for level in inspector.get_levels() for name in sorted(level)]
        n = len(order)

        self.console.print()
        render_title_row(
            self.console,
            self.agent_name,
            validated=True,
            right_meta=f"{n} action{'s' if n != 1 else ''}",
        )
        self.console.print()

        for name in order:
            self.console.print(f"  [green]✓[/green]  {name}", highlight=False)


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
