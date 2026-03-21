"""Inspect graph subcommand."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click
from rich.tree import Tree

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.utils.constants import DEFAULT_ACTION_KIND
from agent_actions.workflow.coordinator import AgentWorkflow

from .inspect_base import BaseInspectCommand

logger = logging.getLogger(__name__)


class GraphCommand(BaseInspectCommand):
    """Show workflow structure as a visual dependency graph."""

    def execute(self, project_root: Path | None = None) -> None:
        workflow = self._load_workflow(project_root=project_root)
        dependency_info = self._analyze_dependencies(workflow)
        execution_order = workflow.execution_order or list(workflow.action_configs.keys())

        if self.json_output:
            self._output_json(workflow, dependency_info, execution_order)
        else:
            self._output_rich(workflow, dependency_info, execution_order)

    def _output_json(
        self,
        workflow: AgentWorkflow,
        dependency_info: dict[str, Any],
        execution_order: list[str],
    ) -> None:
        output = {
            "workflow": self.agent_name,
            "execution_order": execution_order,
            "actions": {
                name: {
                    "type": self._get_action_type(info["input_sources"], info["context_sources"]),
                    "input_sources": info["input_sources"],
                    "context_sources": info["context_sources"],
                    "output_fields": self._get_output_fields(
                        workflow.action_configs.get(name, {}),
                        action_schema=self._get_action_schema(name),
                    ),
                }
                for name, info in dependency_info.items()
            },
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(
        self,
        workflow: AgentWorkflow,
        dependency_info: dict[str, Any],
        execution_order: list[str],
    ) -> None:
        flow_str = " → ".join(execution_order) if execution_order else "none"
        self.console.print(f"[bold cyan]Workflow: {self.agent_name}[/bold cyan]")
        self.console.print(f"[dim]Flow: {flow_str}[/dim]\n")

        tree = Tree("[bold]Actions[/bold]")

        for action_name in execution_order:
            if action_name not in dependency_info:
                continue

            info = dependency_info[action_name]
            action_config = workflow.action_configs.get(action_name, {})
            action_type = self._get_action_type(info["input_sources"], info["context_sources"])

            node = tree.add(f"[bold]{action_name}[/bold] [dim]({action_type})[/dim]")

            kind = action_config.get("kind", DEFAULT_ACTION_KIND)
            if kind != DEFAULT_ACTION_KIND:
                node.add(f"[dim]kind: {kind}[/dim]")

            if info["input_sources"]:
                for src in info["input_sources"]:
                    node.add(f"[green]← {src}[/green]")
            else:
                node.add("[green]← source data[/green]")

            for src in info["context_sources"]:
                node.add(f"[yellow]◇ {src}[/yellow] [dim](context)[/dim]")

            output_fields = self._get_output_fields(
                action_config, action_schema=self._get_action_schema(action_name)
            )
            if output_fields:
                outputs_str = ", ".join(output_fields)
                node.add(f"[magenta]→ {outputs_str}[/magenta]")

        self.console.print(tree)
        self.console.print("\n[dim]← input  ◇ context  → output[/dim]")


@click.command(name="graph")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@handles_user_errors("inspect graph")
@requires_project
def graph(
    agent: str, user_code: str | None, json_output: bool, project_root: Path | None = None
) -> None:
    """
    Show workflow structure as a dependency graph.

    Displays how actions connect: which actions feed into others
    and which provide context data.

    Examples:
        agac inspect graph -a my_workflow
        agac inspect graph -a my_workflow --json
    """
    GraphCommand(agent=agent, user_code=user_code, json_output=json_output).execute(
        project_root=project_root
    )
