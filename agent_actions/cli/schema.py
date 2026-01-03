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

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.cli.renderers import SchemaRenderer
from agent_actions.errors import FileLoadError
from agent_actions.orchestration.agent_workflow import AgentWorkflow, WorkflowConfig, WorkflowPaths
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.response_processing.schema_loader import SchemaLoader
from agent_actions.services import WorkflowSchemaService


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
        self.renderer = SchemaRenderer(self.console)

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

        # Build workflow config for service
        workflow_config = {
            "name": self.agent_name,
            "actions": [
                {**config, "name": name} for name, config in workflow.agent_configs.items()
            ],
        }

        # Get UDF registry (always try to load for tool schemas)
        udf_registry: Dict[str, Any] = {}
        try:
            # pylint: disable=import-outside-toplevel
            from agent_actions.utilities.udf_management.udf_registry import UDF_REGISTRY

            udf_registry = UDF_REGISTRY
        except ImportError:
            pass  # UDF registry not available

        # Create schema loader for external schemas
        schema_loader = SchemaLoader()

        # Create service using unified approach
        service = WorkflowSchemaService(
            workflow_config,
            udf_registry=udf_registry,
            schema_loader=schema_loader,
            project_root=paths.current_dir,
            schema_dir=paths.schema_dir,
        )

        if self.json_output:
            self._output_json(service)
        else:
            self._output_rich(service, workflow.execution_order)

    def _output_json(self, service: WorkflowSchemaService) -> None:
        """Output schemas as JSON."""
        # Build legacy format for backward compatibility
        schemas = {}
        for name, action_schema in service.get_all_schemas().items():
            schemas[name] = {
                "kind": action_schema.kind,
                "input": {
                    "required": action_schema.required_inputs,
                    "optional": action_schema.optional_inputs,
                    "is_template_based": action_schema.is_template_based,
                    "is_dynamic": action_schema.is_dynamic,
                },
                "output": {
                    "fields": action_schema.available_outputs,
                    "is_schemaless": action_schema.is_schemaless,
                    "is_dynamic": action_schema.is_dynamic,
                },
            }
        click.echo(json_lib.dumps(schemas, indent=2))

    def _output_rich(self, service: WorkflowSchemaService, execution_order: list) -> None:
        """Output schemas using rich formatting."""
        schemas = service.get_all_schemas()

        # Use the unified renderer for the summary table
        table = self.renderer.render_summary_table(
            schemas, execution_order, title=f"Action Schemas: {self.agent_name}"
        )
        self.console.print(table)
        self.console.print(f"\n[bold]Total: {len(schemas)} action(s)[/bold]")

        # Show data flow if verbose
        if self.verbose:
            self.console.print("\n")
            panel = self.renderer.render_data_flow_panel(schemas, execution_order)
            self.console.print(panel)


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
