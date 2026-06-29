"""Inspect dependencies subcommand."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click

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
        inspector = self._load_inspector(project_root=project_root)
        dependency_info = self._analyze_dependencies(inspector)

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
            self._output_rich(dependency_info, inspector.execution_order, inspector)

    def _output_json(self, dependency_info: dict[str, Any]) -> None:
        output = {"workflow": self.agent_name, "actions": dependency_info}
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, dependency_info, execution_order, inspector) -> None:
        from agent_actions.cli.inspect_base import compute_graph_hash, render_title_row

        order = [n for n in execution_order if n in dependency_info] or list(dependency_info.keys())
        name_width = max(len(name) for name in order) + 2

        self.console.print()
        render_title_row(
            self.console,
            self.agent_name,
            section="dependency model",
            graph_hash=compute_graph_hash(inspector.action_configs),
        )
        self.console.print()

        for name in order:
            info = dependency_info[name]
            inputs = info["input_sources"]
            # `source` is always-available, not a real context dep.
            contexts = [c for c in info["context_sources"] if c != "source"]

            if inputs:
                inputs_str = ", ".join(inputs)
            else:
                inputs_str = "[dim italic]source data[/dim italic]"

            padded = f"[bold]{name}[/bold]" + " " * (name_width - len(name))
            line = f"  {padded}[dim]←[/dim] {inputs_str}"
            if contexts:
                line += f"   [dim]+ context: {', '.join(contexts)}[/dim]"

            # Source actions already say "source" via `← source data`.
            type_label = self._get_action_type(inputs, contexts).lower()
            if inputs:
                line += f"   [dim]({type_label})[/dim]"
            self.console.print(line, soft_wrap=True)


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
