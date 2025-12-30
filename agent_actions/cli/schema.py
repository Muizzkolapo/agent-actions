"""
Schema command for the Agent Actions CLI.

This module provides the implementation of the 'schema' command,
which displays input and output schemas for all actions in a workflow.
"""

import json as json_lib
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree

from agent_actions.cli.cli_decorators import requires_project, handles_user_errors
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.orchestration.agent_workflow import AgentWorkflow, WorkflowConfig, WorkflowPaths
from agent_actions.validation.static_analyzer import WorkflowStaticAnalyzer
from agent_actions.errors import FileLoadError


class SchemaCommand:  # pylint: disable=too-few-public-methods
    """Implementation of the schema command."""

    def __init__(
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        verbose: bool,
    ):
        """
        Initialize the schema command.

        Args:
            agent: Agent/workflow configuration name
            user_code: Optional path to user code directory containing UDFs
            json_output: Whether to output as JSON
            verbose: Whether to show detailed schema information
        """
        self.agent = agent
        self.agent_name = Path(agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.verbose = verbose
        self.console = Console()

    def _find_config_file(self, config_dir: Path, filename: str) -> Path:
        """Find the configuration file."""
        full_path = config_dir / filename
        if not full_path.exists():
            raise FileLoadError(
                "Configuration file not found",
                context={
                    "file_path": str(full_path),
                    "agent_name": self.agent_name,
                    "suggestion": f"Check if '{filename}' exists in {config_dir}",
                },
            )
        return full_path

    def execute(self) -> None:
        """Execute the schema command."""
        if not self.json_output:
            self.console.print(f"[cyan]Analyzing workflow: {self.agent}[/cyan]\n")

        # Set up paths and load workflow
        paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent)
        filename = f"{self.agent_name}.yml"
        full_path = self._find_config_file(paths.agent_config_dir, filename)

        # Render configuration
        ConfigRenderer.render_and_load_config(
            self.agent_name, full_path, paths.template_dir, paths.rendered_workflows_dir
        )

        # Load workflow to get agent configs
        workflow = AgentWorkflow(
            WorkflowConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.user_code) if self.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=False,
            )
        )

        # Build workflow config for static analyzer
        workflow_config = {
            "actions": [{**config, "name": name} for name, config in workflow.agent_configs.items()]
        }

        # Get UDF registry if user code provided
        udf_registry: Dict[str, Any] = {}
        if self.user_code:
            from agent_actions.utilities.udf_management.udf_registry import (  # pylint: disable=import-outside-toplevel
                UDF_REGISTRY,
            )

            udf_registry = UDF_REGISTRY

        # Create analyzer and get schemas
        analyzer = WorkflowStaticAnalyzer(workflow_config, udf_registry=udf_registry)
        schemas = analyzer.get_action_schemas()

        if self.json_output:
            self._output_json(schemas)
        else:
            self._output_rich(schemas, workflow.execution_order)

    def _output_json(self, schemas: Dict[str, Dict[str, Any]]) -> None:
        """Output schemas as JSON."""
        click.echo(json_lib.dumps(schemas, indent=2))

    def _output_rich(self, schemas: Dict[str, Dict[str, Any]], execution_order: list) -> None:
        """Output schemas using rich formatting."""
        # Create table
        table = Table(title=f"Action Schemas: {self.agent_name}", show_lines=True)
        table.add_column("Action", style="cyan", no_wrap=True)
        table.add_column("Type", style="magenta", width=6)
        table.add_column("Input", style="green")
        table.add_column("Output", style="yellow")

        # Add rows in execution order
        for action_name in execution_order:
            if action_name not in schemas:
                continue

            info = schemas[action_name]

            # Format input
            input_str = self._format_input(info["input"])

            # Format output
            output_str = self._format_output(info["output"])

            table.add_row(action_name, info["kind"], input_str, output_str)

        self.console.print(table)
        self.console.print(f"\n[bold]Total: {len(schemas)} action(s)[/bold]")

        # Show data flow if verbose
        if self.verbose:
            self._show_data_flow(schemas, execution_order)

    def _format_input(self, input_info: Dict[str, Any]) -> str:
        """Format input schema for display."""
        if input_info.get("is_template_based"):
            return "[dim](template-based)[/dim]"
        if input_info.get("is_dynamic"):
            return "[dim](dynamic)[/dim]"

        parts = []
        if input_info.get("required"):
            parts.append(f"[bold]required:[/bold] {', '.join(input_info['required'])}")
        if input_info.get("optional"):
            parts.append(f"[dim]optional:[/dim] {', '.join(input_info['optional'])}")

        return "\n".join(parts) if parts else "[dim](none)[/dim]"

    def _format_output(self, output_info: Dict[str, Any]) -> str:
        """Format output schema for display."""
        if output_info.get("is_schemaless"):
            return "[dim](schemaless)[/dim]"
        if output_info.get("is_dynamic"):
            return "[dim](dynamic)[/dim]"

        fields = output_info.get("fields", [])
        return ", ".join(fields) if fields else "[dim](none)[/dim]"

    def _show_data_flow(self, schemas: Dict[str, Dict[str, Any]], execution_order: list) -> None:
        """Show data flow visualization."""
        self.console.print("\n")

        tree = Tree("[bold]Data Flow[/bold]")

        for action_name in execution_order:
            if action_name not in schemas:
                continue

            info = schemas[action_name]
            action_tree = tree.add(f"[cyan]{action_name}[/cyan] ({info['kind']})")

            # Input
            input_branch = action_tree.add("[green]Input[/green]")
            if info["input"].get("is_template_based"):
                input_branch.add("[dim]template-based[/dim]")
            elif info["input"].get("is_dynamic"):
                input_branch.add("[dim]dynamic[/dim]")
            else:
                for field in info["input"].get("required", []):
                    input_branch.add(f"[bold]{field}[/bold] (required)")
                for field in info["input"].get("optional", []):
                    input_branch.add(f"{field} (optional)")

            # Output
            output_branch = action_tree.add("[yellow]Output[/yellow]")
            if info["output"].get("is_schemaless"):
                output_branch.add("[dim]schemaless[/dim]")
            elif info["output"].get("is_dynamic"):
                output_branch.add("[dim]dynamic[/dim]")
            else:
                for field in info["output"].get("fields", []):
                    output_branch.add(field)

        self.console.print(Panel(tree, title="Workflow Data Flow"))


@click.command(name="schema")
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent/workflow configuration name (without path or extension)",
)
@click.option(
    "-u",
    "--user-code",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to user code directory containing UDFs (for tool input schemas)",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output as JSON for programmatic use",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed data flow visualization",
)
@handles_user_errors("schema")
@requires_project
def schema(
    agent: str,
    user_code: Optional[str],
    json_output: bool,
    verbose: bool,
) -> None:
    """
    Display input and output schemas for all actions in a workflow.

    Shows what fields each action expects as input and produces as output,
    enabling static analysis of data flow through the workflow.

    Examples:
        agac schema -a my_workflow
        agac schema -a my_workflow --json
        agac schema -a my_workflow -u ./user_code --verbose
    """
    command = SchemaCommand(agent, user_code, json_output, verbose)
    command.execute()
