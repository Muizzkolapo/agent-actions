"""Inspect commands for the Agent Actions CLI.

Unified preflight and introspection surface.

Surface:

    agac inspect -a <workflow>             # graph + validation status
    agac inspect -a <workflow> --yaml      # rendered YAML
    agac inspect -a <workflow> --validate  # validation report (pass/fail)
    agac inspect -a <workflow> --dry-run   # graph + validation + estimate
    agac inspect -a <workflow> --json      # JSON output (combines with above)

    agac inspect graph     -a <workflow>
    agac inspect deps      -a <workflow>
    agac inspect action    -a <workflow> ACTION
    agac inspect context   -a <workflow> ACTION
"""

from __future__ import annotations

import json as json_lib
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import _format_project_root_display, handles_user_errors
from agent_actions.errors.base import AgentActionsError
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.project_root import ensure_in_project

from .inspect_action import ActionCommand, ContextCommand, action, context
from .inspect_base import BaseInspectCommand
from .inspect_deps import DependenciesCommand, dependencies
from .inspect_graph import GraphCommand, graph


class InspectCommand(BaseInspectCommand):
    """Default ``agac inspect`` — graph + validation, or one of the flag modes."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        yaml_output: bool,
        json_output: bool,
        validate_only: bool,
        dry_run: bool,
    ):
        super().__init__(agent, user_code, json_output)
        self.yaml_output = yaml_output
        self.validate_only = validate_only
        self.dry_run = dry_run

    def execute(self, project_root: Path | None = None) -> None:
        if self.yaml_output:
            inspector = WorkflowInspector(
                agent_name=self.agent_name,
                project_root=project_root,
                user_code_path=self.user_code,
            )
            click.echo(inspector.render())
            return

        inspector = self._load_inspector(project_root=project_root)

        if self.validate_only:
            self._output_validation(inspector)
            return
        if self.dry_run:
            self._output_dry_run(inspector)
            return
        self._output_graph_with_validation(inspector)

    # ── --validate ───────────────────────────────────────────────────

    def _output_validation(self, inspector: WorkflowInspector) -> None:
        if self.json_output:
            click.echo(
                json_lib.dumps(
                    {"workflow": self.agent_name, "status": "ok"},
                    indent=2,
                )
            )
            return
        self.console.print(f"[green]✅ {self.agent_name}: validation passed[/green]")

    # ── --dry-run ────────────────────────────────────────────────────

    def _output_dry_run(self, inspector: WorkflowInspector) -> None:
        levels = inspector.get_levels()
        scope = inspector.get_context_scope()
        estimate = inspector.estimate()

        if self.json_output:
            click.echo(
                json_lib.dumps(
                    {
                        "workflow": self.agent_name,
                        "status": "ok",
                        "execution_levels": levels,
                        "context_scope": scope,
                        "estimate": estimate,
                    },
                    indent=2,
                )
            )
            return

        self.console.print(f"[bold cyan]Preflight: {self.agent_name}[/bold cyan]\n")
        self.console.print("[bold]Execution levels[/bold]")
        level_width = len(str(len(levels)))
        for i, level in enumerate(levels, 1):
            self.console.print(
                f"  [dim]L{i:>{level_width}}[/dim]  {', '.join(level)}", soft_wrap=True
            )
        if scope:
            self.console.print("\n[bold]Context scope[/bold] [dim](empty fields omitted)[/dim]")
            for name, info in scope.items():
                line = self._format_scope_line(name, info.get("scope"))
                if line is not None:
                    self.console.print(f"  {line}", soft_wrap=True)
        self.console.print(
            f"\n[bold]Estimate[/bold]  {estimate['action_count']} actions, "
            f"{estimate['llm_calls']} LLM calls, "
            f"{estimate['guarded_actions']} guarded"
        )

    @staticmethod
    def _format_scope_line(action_name: str, action_scope: object) -> str | None:
        """Render an action's context_scope on one line, skipping empty kinds."""
        if isinstance(action_scope, str):
            return f"[bold]{action_name}[/bold] [dim]→[/dim] {action_scope}"
        if not isinstance(action_scope, dict):
            return None
        parts: list[str] = []
        for kind in ("observe", "passthrough", "drop"):
            items = action_scope.get(kind) or []
            if not items:
                continue
            parts.append(f"[cyan]{kind}[/cyan]={', '.join(items)}")
        if not parts:
            return None
        return f"[bold]{action_name}[/bold] [dim]→[/dim] {'; '.join(parts)}"

    # ── default (no flags) ───────────────────────────────────────────

    def _output_graph_with_validation(self, inspector: WorkflowInspector) -> None:
        levels = inspector.get_levels()
        scope = inspector.get_context_scope()

        if self.json_output:
            click.echo(
                json_lib.dumps(
                    {
                        "workflow": self.agent_name,
                        "status": "ok",
                        "execution_levels": levels,
                        "context_scope": scope,
                    },
                    indent=2,
                )
            )
            return

        action_count = sum(len(lvl) for lvl in levels)
        parallel_count = sum(1 for lvl in levels if len(lvl) > 1)
        estimate = inspector.estimate()

        # Visual hierarchy:
        #   row 1 = identity (workflow name) + status pill — eye lands first
        #   row 2 = stats subtitle — answers "how big? how expensive?"
        #   blank line — section break
        #   "Pipeline:" header — labels the body
        #   blank line — breathing room
        #   numbered steps — left-anchored for fast scan
        self.console.print(
            f"\n  [bold cyan]{self.agent_name}[/bold cyan]  [bold green]✅ validated[/bold green]"
        )
        self.console.print(
            f"  [dim]{action_count} actions, {estimate['llm_calls']} LLM calls, "
            f"{estimate['guarded_actions']} guarded · "
            f"{len(levels)} levels, {parallel_count} parallel groups[/dim]"
        )
        self.console.print()
        self.console.print("  [bold]Pipeline[/bold]")
        self.console.print()

        # Chunk levels into "steps" — what the user thinks of as one
        # conceptual unit: either a fan-out (parallel level) or a run of
        # serial actions. Step numbering is more conversational than
        # leaking L-numbers; --dry-run keeps L-numbers for accuracy.
        steps = self._build_steps(levels)
        step_width = len(str(len(steps)))

        for step_num, step in enumerate(steps, 1):
            label = f"[dim]{step_num:>{step_width}}.[/dim]"
            if step["kind"] == "parallel":
                self._print_parallel(label, step["actions"])
            else:
                self._print_chain(label, step["actions"])

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

    def _print_chain(self, label: str, actions: list[str]) -> None:
        """Render a serial chain, wrapping with consistent continuation
        indent so long chains don't run off screen as one wall of text.
        """
        prefix = f"  {label}  [green]→[/green] "
        cont = "       [dim]→[/dim] "
        self._print_wrapped(prefix, cont, " [dim]→[/dim] ", actions)

    def _print_parallel(self, label: str, actions: list[str]) -> None:
        """Render a parallel fan-out, wrapping member lists the same way
        so a 7-way fan doesn't blow past the terminal width.
        """
        prefix = f"  {label}  [bold yellow]⫻[/bold yellow] [dim]{len(actions)} parallel:[/dim]  "
        cont = "                       "
        self._print_wrapped(prefix, cont, ", ", actions)

    def _print_wrapped(
        self,
        prefix: str,
        cont: str,
        separator: str,
        items: list[str],
    ) -> None:
        """Greedy line packer for a prefixed, separator-joined list."""
        import re

        def _visible(s: str) -> int:
            return len(re.sub(r"\[/?[^\]]+\]", "", s))

        width = max(self.console.width or 80, 60)
        line = prefix + items[0]
        for nxt in items[1:]:
            tentative = f"{line}{separator}{nxt}"
            if _visible(tentative) > width:
                self.console.print(line, soft_wrap=False)
                line = cont + nxt
            else:
                line = tentative
        self.console.print(line, soft_wrap=False)


@click.group(name="inspect", invoke_without_command=True)
@click.option("-a", "--agent", "agent_opt", required=False, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option(
    "--yaml",
    "yaml_output",
    is_flag=True,
    help="Output rendered YAML",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--validate",
    "validate_only",
    is_flag=True,
    help="Validation report only (pass/fail)",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Full preflight: graph + validate + estimate",
)
@click.pass_context
@handles_user_errors("inspect")
def inspect(
    ctx: click.Context,
    agent_opt: str | None,
    user_code: str | None,
    yaml_output: bool,
    json_output: bool,
    validate_only: bool,
    dry_run: bool,
) -> None:
    """Inspect workflow structure, data flow, and validation status.

    Default (no flags): dependency graph with validation status.

    \b
    Examples:
        agac inspect -a my_workflow              # graph + validation
        agac inspect -a my_workflow --yaml       # rendered YAML
        agac inspect -a my_workflow --validate   # validation pass/fail
        agac inspect -a my_workflow --dry-run    # full preflight report
        agac inspect -a my_workflow --json       # JSON output
    """
    # Mutex checks must precede subcommand routing — otherwise the early
    # return below silently drops group flags into a subcommand path that
    # ignores them.
    flag_count = sum([yaml_output, validate_only, dry_run])
    if flag_count > 1:
        raise click.UsageError("Only one of --yaml, --validate, --dry-run may be used at a time.")
    if yaml_output and json_output:
        raise click.UsageError("--yaml and --json cannot be combined; --yaml emits raw YAML.")
    if ctx.invoked_subcommand is not None and (yaml_output or validate_only or dry_run):
        raise click.UsageError(
            "--yaml, --validate, and --dry-run apply to the default "
            "`agac inspect -a <wf>` form only — do not combine them with a subcommand."
        )

    # ``default_map`` forwards group-level ``-a`` / ``-u`` to the
    # subcommand so ``agac inspect -a foo graph`` works (subcommands
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

    cmd = InspectCommand(
        agent=agent_opt,
        user_code=user_code,
        yaml_output=yaml_output,
        json_output=json_output,
        validate_only=validate_only,
        dry_run=dry_run,
    )
    # --json catches every AgentActionsError (not just preflight) so CI
    # scripts parsing stdout see ``{status: failed, ...}`` for missing
    # workflows, config errors, or a missing project root too.
    try:
        project_root = ensure_in_project()
        # Only print the project-root banner when there's something to
        # learn from it — running from a sub-directory of the project. If
        # cwd == project_root the banner just shows "." which is noise.
        display = _format_project_root_display(project_root)
        if display != ".":
            click.echo(f"\U0001f4c1 Project root: {display}", err=True)
        cmd.execute(project_root=project_root)
    except AgentActionsError as exc:
        if not json_output:
            raise
        click.echo(
            json_lib.dumps(
                {
                    "workflow": cmd.agent_name,
                    "status": "failed",
                    "error": str(exc),
                },
                indent=2,
            )
        )
        raise click.exceptions.Exit(1) from exc


inspect.add_command(dependencies)
inspect.add_command(graph)
inspect.add_command(action)
inspect.add_command(context)

__all__ = [
    "inspect",
    "BaseInspectCommand",
    "DependenciesCommand",
    "GraphCommand",
    "ActionCommand",
    "ContextCommand",
    "InspectCommand",
]
