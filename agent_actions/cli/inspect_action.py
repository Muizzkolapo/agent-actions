"""Inspect action and context subcommands."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.output.response.config_fields import get_default
from agent_actions.utils.constants import DEFAULT_ACTION_KIND

from .inspect_base import BaseInspectCommand

logger = logging.getLogger(__name__)


class ActionCommand(BaseInspectCommand):
    """Show detailed information about a single action."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.action_name = action_name

    def execute(self, project_root: Path | None = None) -> None:
        workflow = self._load_workflow(project_root=project_root)

        if self.action_name not in workflow.action_configs:
            available = ", ".join(workflow.action_configs.keys())
            raise click.ClickException(
                f"Action '{self.action_name}' not found. Available: {available}"
            )

        action_config = workflow.action_configs[self.action_name]
        dependency_info = self._analyze_dependencies(workflow)
        info = dependency_info[self.action_name]

        if self.json_output:
            self._output_json(action_config, info)
        else:
            self._output_rich(action_config, info)

    def _output_json(self, action_config: dict[str, Any], info: dict[str, Any]) -> None:
        output = {
            "workflow": self.agent_name,
            "action": self.action_name,
            "type": self._get_action_type(info["input_sources"], info["context_sources"]),
            "kind": action_config.get("kind", DEFAULT_ACTION_KIND),
            "model": action_config.get("model_name"),
            "input_sources": info["input_sources"],
            "context_sources": info["context_sources"],
            "context_scope": info["context_scope"],
            "output_fields": self._get_output_fields(
                action_config,
                action_schema=self._get_action_schema(self.action_name),
            ),
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, action_config: dict[str, Any], info: dict[str, Any]) -> None:
        action_type = self._get_action_type(info["input_sources"], info["context_sources"])

        self.console.print(f"[bold cyan]Action: {self.action_name}[/bold cyan]")
        self.console.print(f"[dim]Type: {action_type}[/dim]\n")

        kind = action_config.get("kind", DEFAULT_ACTION_KIND)
        model = action_config.get("model_name", "default")
        granularity = action_config.get("granularity", get_default("granularity"))

        config_table = Table(show_header=False, box=None, padding=(0, 2))
        config_table.add_column(style="bold")
        config_table.add_column()
        config_table.add_row("Kind:", kind)
        config_table.add_row("Model:", model)
        config_table.add_row("Granularity:", granularity)
        self.console.print(Panel(config_table, title="Configuration", border_style="dim"))

        tree = Tree("[bold]Dependencies[/bold]")

        if info["input_sources"]:
            branch = tree.add("[green]Input Sources[/green]")
            for src in info["input_sources"]:
                branch.add(f"• {src}")
        else:
            tree.add("[green]Input Sources[/green]: [dim]source data[/dim]")

        if info["context_sources"]:
            branch = tree.add("[yellow]Context Sources[/yellow]")
            for src in info["context_sources"]:
                branch.add(f"• {src}")
        else:
            tree.add("[yellow]Context Sources[/yellow]: [dim]none[/dim]")

        self.console.print(tree)

        ctx = info["context_scope"]
        if ctx["observe"] or ctx["passthrough"]:
            self.console.print()
            scope_tree = Tree("[bold]Input Fields (from context_scope)[/bold]")
            if ctx["observe"]:
                obs = scope_tree.add("[cyan]observe:[/cyan]")
                for f in ctx["observe"]:
                    obs.add(f"• {f}")
            if ctx["passthrough"]:
                pas = scope_tree.add("[cyan]passthrough:[/cyan]")
                for f in ctx["passthrough"]:
                    pas.add(f"• {f}")
            self.console.print(scope_tree)

        output_fields = self._get_output_fields(
            action_config,
            action_schema=self._get_action_schema(self.action_name),
        )
        if output_fields:
            self.console.print()
            out_tree = Tree("[bold]Output Fields (from schema)[/bold]")
            for f in output_fields:
                out_tree.add(f"[magenta]• {f}[/magenta]")
            self.console.print(out_tree)


@click.command(name="action")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name")
@handles_user_errors("inspect action")
@requires_project
def action(
    agent: str,
    user_code: str | None,
    json_output: bool,
    action_name: str,
    project_root: Path | None = None,
) -> None:
    """
    Show details for a specific action.

    Displays configuration, dependencies, and context scope.

    Examples:
        agac inspect action -a my_workflow extract_facts
        agac inspect action -a my_workflow generate_question --json
    """
    ActionCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute(project_root=project_root)


class ContextCommand(BaseInspectCommand):
    """Show context debug information for a specific action."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.target_action_name = action_name

    def execute(self, project_root: Path | None = None) -> None:
        workflow = self._load_workflow(project_root=project_root)

        if self.target_action_name not in workflow.action_configs:
            available = ", ".join(workflow.action_configs.keys())
            raise click.ClickException(
                f"Action '{self.target_action_name}' not found. Available: {available}"
            )

        action_config = workflow.action_configs[self.target_action_name]
        dependency_info = self._analyze_dependencies(workflow)
        info = dependency_info[self.target_action_name]

        context_data = self._build_context_data(workflow, action_config, info)

        if self.json_output:
            self._output_json(context_data)
        else:
            self._output_rich(context_data)

    def _build_context_data(
        self,
        workflow,
        action_config: dict[str, Any],
        info: dict[str, Any],
    ) -> dict[str, Any]:
        namespaces = {}
        namespaces["source"] = ["[from source data]"]

        for dep in info["input_sources"]:
            dep_config = workflow.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            namespaces[dep] = dep_fields if dep_fields else ["[schema fields]"]

        for dep in info["context_sources"]:
            dep_config = workflow.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            namespaces[dep] = dep_fields if dep_fields else ["[schema fields]"]

        namespaces["version"] = ["i", "idx", "length", "first", "last"]
        namespaces["workflow"] = ["name", "run_id"]

        context_scope = action_config.get("context_scope", {})
        output_fields = self._get_output_fields(
            action_config, action_schema=self._get_action_schema(self.target_action_name)
        )
        total_vars = sum(len(fields) for fields in namespaces.values())

        return {
            "action_name": self.target_action_name,
            "workflow": self.agent_name,
            "namespaces": namespaces,
            "context_scope": {
                "observe": context_scope.get("observe", []),
                "passthrough": context_scope.get("passthrough", []),
                "drop": context_scope.get("drop", []),
            },
            "dependencies": {
                "input_sources": info["input_sources"],
                "context_sources": info["context_sources"],
            },
            "output_fields": output_fields,
            "total_template_variables": total_vars,
        }

    def _output_json(self, context_data: dict[str, Any]) -> None:
        click.echo(json_lib.dumps(context_data, indent=2))

    def _output_rich(self, context_data: dict[str, Any]) -> None:
        action_name = context_data["action_name"]

        self.console.print()
        self.console.print(
            f"[bold cyan]=== Context Debug for action '{action_name}' ===[/bold cyan]"
        )
        self.console.print()

        namespaces = context_data.get("namespaces", {})
        if namespaces:
            tree = Tree("[bold]Namespaces loaded:[/bold]")
            for ns, fields in namespaces.items():
                field_str = ", ".join(fields[:5])
                if len(fields) > 5:
                    field_str += f"... (+{len(fields) - 5} more)"
                tree.add(f"[green]{ns}[/green]: {len(fields)} fields [{field_str}]")
            self.console.print(tree)
            self.console.print()

        scope = context_data.get("context_scope", {})
        if scope.get("observe") or scope.get("passthrough") or scope.get("drop"):
            tree = Tree("[bold]Context scope applied:[/bold]")
            if scope.get("observe"):
                tree.add(f"[cyan]observe:[/cyan] {', '.join(scope['observe'])}")
            if scope.get("passthrough"):
                tree.add(f"[cyan]passthrough:[/cyan] {', '.join(scope['passthrough'])}")
            if scope.get("drop"):
                tree.add(f"[cyan]drop:[/cyan] {', '.join(scope['drop'])}")
            self.console.print(tree)
            self.console.print()

        if namespaces:
            tree = Tree("[bold]Template variables available:[/bold]")
            for ns, fields in namespaces.items():
                vars_str = ", ".join(f"{{{{ {ns}.{f} }}}}" for f in fields[:3])
                if len(fields) > 3:
                    vars_str += f", ... (+{len(fields) - 3} more)"
                tree.add(f"[magenta]{vars_str}[/magenta]")
            self.console.print(tree)
            self.console.print()

        deps = context_data.get("dependencies", {})
        if deps.get("input_sources") or deps.get("context_sources"):
            tree = Tree("[bold]Dependencies:[/bold]")
            if deps.get("input_sources"):
                tree.add(f"[green]input_sources:[/green] {', '.join(deps['input_sources'])}")
            if deps.get("context_sources"):
                tree.add(f"[yellow]context_sources:[/yellow] {', '.join(deps['context_sources'])}")
            self.console.print(tree)
            self.console.print()

        output_fields = context_data.get("output_fields", [])
        if output_fields:
            tree = Tree("[bold]Output fields (from schema):[/bold]")
            for f in output_fields:
                tree.add(f"[magenta]{f}[/magenta]")
            self.console.print(tree)
            self.console.print()


@click.command(name="context")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name")
@handles_user_errors("inspect context")
@requires_project
def context(
    agent: str,
    user_code: str | None,
    json_output: bool,
    action_name: str,
    project_root: Path | None = None,
) -> None:
    """
    Show context debug information for a specific action.

    Displays available namespaces, context scope rules, and template variables
    that would be available during template rendering.

    Examples:
        agac inspect context -a my_workflow extract_facts
        agac inspect context -a my_workflow generate_question --json
    """
    ContextCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute(project_root=project_root)
