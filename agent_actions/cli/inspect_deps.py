"""Inspect dependencies subcommand."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click
from rich.table import Table

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project

from .inspect_base import BaseInspectCommand

logger = logging.getLogger(__name__)


class DependenciesCommand(BaseInspectCommand):
    """Show dependency analysis in table format."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        action_filter: str | None,
    ):
        super().__init__(agent, user_code, json_output)
        self.action_filter = action_filter

    def execute(self, project_root: Path | None = None) -> None:
        if not self.json_output:
            self.console.print(f"[cyan]Dependency Analysis: {self.agent_name}[/cyan]\n")

        workflow = self._load_workflow(project_root=project_root)
        dependency_info = self._analyze_dependencies(workflow)

        if self.action_filter:
            if self.action_filter not in dependency_info:
                available = ", ".join(dependency_info.keys())
                raise click.ClickException(
                    f"Action '{self.action_filter}' not found. Available: {available}"
                )
            dependency_info = {self.action_filter: dependency_info[self.action_filter]}

        if self.json_output:
            self._output_json(dependency_info)
        else:
            self._output_rich(dependency_info, workflow.execution_order)

    def _output_json(self, dependency_info: dict[str, Any]) -> None:
        output = {"workflow": self.agent_name, "actions": dependency_info}
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, dependency_info: dict[str, Any], execution_order: list) -> None:
        table = Table(title="Dependency Model", show_lines=True)
        table.add_column("Action", style="bold")
        table.add_column("Input Sources", style="green")
        table.add_column("Context Sources", style="yellow")
        table.add_column("Type", style="cyan")

        order = execution_order if execution_order else list(dependency_info.keys())
        for name in order:
            if name not in dependency_info:
                continue
            info = dependency_info[name]
            inputs = info["input_sources"]
            contexts = info["context_sources"]

            input_str = ", ".join(inputs) if inputs else "[dim]source data[/dim]"
            context_str = ", ".join(contexts) if contexts else "[dim]none[/dim]"
            action_type = self._get_action_type(inputs, contexts)

            table.add_row(name, input_str, context_str, action_type)

        self.console.print(table)


@click.command(name="dependencies")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--action", "action_filter", required=False, help="Filter to specific action")
@handles_user_errors("inspect dependencies")
@requires_project
def dependencies(
    agent: str,
    user_code: str | None,
    json_output: bool,
    action_filter: str | None,
    project_root: Path | None = None,
) -> None:
    """
    Analyze workflow dependencies and auto-inferred context.

    Shows input sources (execution dependencies) and context sources
    (auto-inferred from context_scope) for each action.

    Examples:
        agac inspect dependencies -a my_workflow
        agac inspect dependencies -a my_workflow --action extract_facts
    """
    DependenciesCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_filter=action_filter
    ).execute(project_root=project_root)
