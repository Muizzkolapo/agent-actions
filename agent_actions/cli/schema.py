"""Schema command for the Agent Actions CLI."""

import json as json_lib
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.renderers import SchemaRenderer
from agent_actions.config.project_paths import ProjectPathsFactory, find_config_file
from agent_actions.errors import DependencyError
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.workflow import WorkflowSchemaService
from agent_actions.workflow.coordinator import AgentWorkflow, WorkflowPaths, WorkflowRuntimeConfig


class SchemaCommand:
    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        verbose: bool,
    ):
        self.agent = agent
        self.agent_name = Path(agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.verbose = verbose
        self.console = Console()
        self.renderer = SchemaRenderer(self.console)

    def execute(self, project_root: Path | None = None) -> None:
        if not self.json_output:
            self.console.print(f"[cyan]Analyzing workflow: {self.agent}[/cyan]\n")

        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent, auto_create=False, project_root=project_root
        )
        filename = f"{self.agent_name}.yml"
        full_path = find_config_file(
            self.agent_name, paths.agent_config_dir, filename, check_alternatives=True
        )

        ConfigRenderingService().render_and_load_config(
            self.agent_name, full_path, paths.template_dir, project_root=project_root
        )

        workflow = AgentWorkflow(
            WorkflowRuntimeConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.user_code) if self.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=False,
                project_root=project_root,
            )
        )

        workflow_config = WorkflowSchemaService.build_workflow_config(
            self.agent_name, workflow.action_configs
        )

        try:
            from agent_actions.utils.udf_management.registry import UDF_REGISTRY

            udf_registry: dict[str, Any] = UDF_REGISTRY
        except ImportError as e:
            raise DependencyError(
                f"Failed to import UDF registry: {e}. "
                "Ensure agent_actions.utils.udf_management.registry is accessible "
                "and any user code provided via --user-code has no syntax errors."
            ) from e

        schema_loader = SchemaLoader()

        service = WorkflowSchemaService(
            workflow_config,
            udf_registry=udf_registry,
            schema_loader=schema_loader,
            project_root=paths.current_dir,
        )

        if self.json_output:
            self._output_json(service)
        else:
            self._output_rich(service, workflow.execution_order)

    def _output_json(self, service: WorkflowSchemaService) -> None:
        schemas = {}
        for name, action_schema in service.get_all_schemas().items():
            schemas[name] = {
                "kind": action_schema.kind.value,
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
        schemas = service.get_all_schemas()

        table = self.renderer.render_summary_table(
            schemas, execution_order, title=f"Action Schemas: {self.agent_name}"
        )
        self.console.print(table)
        self.console.print(f"\n[bold]Total: {len(schemas)} action(s)[/bold]")

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
    user_code: str | None,
    json_output: bool,
    verbose: bool,
    project_root: Path | None = None,
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
    command.execute(project_root=project_root)
