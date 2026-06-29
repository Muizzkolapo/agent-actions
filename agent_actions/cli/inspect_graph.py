"""Inspect graph subcommand."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.constants import DEFAULT_ACTION_KIND

from .inspect_base import BaseInspectCommand

logger = logging.getLogger(__name__)


class GraphCommand(BaseInspectCommand):
    """Show workflow structure as a visual dependency graph."""

    def execute(self, project_root: Path | None = None) -> None:
        inspector = self._load_inspector(project_root=project_root)
        dependency_info = self._analyze_dependencies(inspector)
        execution_order = inspector.execution_order or list(inspector.action_configs.keys())

        if self.json_output:
            self._output_json(inspector, dependency_info, execution_order)
        else:
            self._output_rich(inspector, dependency_info, execution_order)

    def _output_json(
        self,
        inspector: WorkflowInspector,
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
                        inspector.action_configs.get(name, {}),
                        action_schema=self._get_action_schema(name),
                    ),
                }
                for name, info in dependency_info.items()
            },
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(
        self,
        inspector: WorkflowInspector,
        dependency_info: dict[str, Any],
        execution_order: list[str],
    ) -> None:
        """Per-action block view — same arrows the rest of the family
        uses: ``←`` for inputs, ``+`` for context-only sources,
        ``→`` for outputs. One block per action in execution order.
        """
        self.console.print(
            f"\n  [bold cyan]{self.agent_name}[/bold cyan]   [dim]workflow graph[/dim]"
        )
        self.console.print(f"  [dim]{len(execution_order)} actions[/dim]\n")

        for action_name in execution_order:
            if action_name not in dependency_info:
                continue

            info = dependency_info[action_name]
            action_config = inspector.action_configs.get(action_name, {})
            kind = action_config.get("kind", DEFAULT_ACTION_KIND)
            inputs = info["input_sources"]
            contexts = [c for c in info["context_sources"] if c != "source"]
            outputs = self._get_output_fields(
                action_config, action_schema=self._get_action_schema(action_name)
            )

            kind_tag = "" if kind == DEFAULT_ACTION_KIND else f"  [dim]({kind})[/dim]"
            self.console.print(f"  [bold]{action_name}[/bold]{kind_tag}")

            if inputs:
                self.console.print(f"    [green]←[/green] {', '.join(inputs)}", soft_wrap=True)
            else:
                self.console.print("    [green]←[/green] [italic dim]source data[/italic dim]")
            if contexts:
                self.console.print(
                    f"    [yellow]+[/yellow] [dim]context:[/dim] {', '.join(contexts)}",
                    soft_wrap=True,
                )
            if outputs:
                self.console.print(
                    f"    [magenta]→[/magenta] {', '.join(outputs)}",
                    soft_wrap=True,
                    highlight=False,
                )
            self.console.print()


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
