"""Inspect commands for the Agent Actions CLI.

Unified preflight + introspection. Replaces ``agac compile`` and
``agac render`` — the rendered-YAML output now lives behind
``agac inspect --yaml`` (VIOL-0008).

Surface:

    agac inspect -a <workflow>             # graph + validation status
    agac inspect -a <workflow> --yaml      # rendered YAML (was: agac compile)
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
from rich.tree import Tree

from agent_actions.cli.cli_decorators import handles_user_errors
from agent_actions.errors.preflight import PreFlightValidationError
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
        # --yaml is the compile replacement — skip validation, render only.
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
        # _load_inspector already ran validation successfully (it raises
        # on failure), so reaching here means the workflow is valid.
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
        self.console.print("[bold]Execution levels:[/bold]")
        for i, level in enumerate(levels, 1):
            self.console.print(f"  Level {i}: {', '.join(level)}")
        if scope:
            self.console.print("\n[bold]Context scope:[/bold]")
            for name, info in scope.items():
                self.console.print(f"  {name} → {info['scope']}")
        self.console.print(
            f"\n[bold]Estimate:[/bold] {estimate['action_count']} actions, "
            f"{estimate['llm_calls']} LLM calls, "
            f"{estimate['guarded_actions']} guarded"
        )

    # ── default (no flags) ───────────────────────────────────────────

    def _output_graph_with_validation(self, inspector: WorkflowInspector) -> None:
        levels = inspector.get_levels()
        scope = inspector.get_context_scope()

        if self.json_output:
            # "status: ok" mirrors --validate / --dry-run JSON output so
            # CI consumers can branch on a single key. We only ever reach
            # this code path on success — failures raise upstream.
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

        self.console.print(f"\n[bold cyan]✅ Workflow: {self.agent_name}[/bold cyan]\n")
        tree = Tree("[bold]Actions[/bold]")
        for i, level in enumerate(levels, 1):
            level_node = tree.add(f"[dim]Level {i}[/dim]")
            for action_name in level:
                action_scope = scope.get(action_name, {}).get("scope", "observe")
                if isinstance(action_scope, dict):
                    # Summarize compactly
                    parts = []
                    for kind in ("observe", "passthrough", "drop"):
                        items = action_scope.get(kind) or []
                        if items:
                            parts.append(f"{kind}={len(items)}")
                    scope_str = ", ".join(parts) if parts else "observe"
                else:
                    scope_str = str(action_scope)
                level_node.add(f"{action_name} [dim]({scope_str})[/dim]")
        self.console.print(tree)


@click.group(name="inspect", invoke_without_command=True)
@click.option("-a", "--agent", "agent_opt", required=False, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option(
    "--yaml",
    "yaml_output",
    is_flag=True,
    help="Output rendered YAML (replaces 'agac compile')",
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
    # Subcommand routing: subcommands manage their own options and
    # project-root injection via @requires_project.
    if ctx.invoked_subcommand is not None:
        return

    if not agent_opt:
        raise click.UsageError(
            "Missing required option '-a' / '--agent'. Run 'agac inspect --help' for usage."
        )

    flag_count = sum([yaml_output, validate_only, dry_run])
    if flag_count > 1:
        raise click.UsageError("Only one of --yaml, --validate, --dry-run may be used at a time.")

    project_root = ensure_in_project()
    cwd = Path.cwd()
    try:
        rel_path = project_root.relative_to(cwd)
        display_path = f"./{rel_path}" if str(rel_path) != "." else "."
    except ValueError:
        display_path = str(project_root)
    click.echo(f"\U0001f4c1 Project root: {display_path}", err=True)

    cmd = InspectCommand(
        agent=agent_opt,
        user_code=user_code,
        yaml_output=yaml_output,
        json_output=json_output,
        validate_only=validate_only,
        dry_run=dry_run,
    )
    try:
        cmd.execute(project_root=project_root)
    except PreFlightValidationError as exc:
        # JSON consumers need a machine-readable failure body on stdout,
        # which @handles_user_errors can't produce. For non-JSON modes we
        # fall through to the standard error-formatting decorator so the
        # default/--validate/--dry-run paths all surface failures with a
        # single banner — no double-print.
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
