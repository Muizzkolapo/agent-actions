"""
Inspect commands for the Agent Actions CLI.

This module provides the implementation of the 'inspect' command group,
which includes subcommands for analyzing workflow structure and data flow.
"""

import json as json_lib
from pathlib import Path
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from agent_actions.cli.renderers import SchemaRenderer
from agent_actions.errors import FileLoadError
from agent_actions.orchestration.agent_workflow import AgentWorkflow, WorkflowConfig, WorkflowPaths
from agent_actions.prompt_generation.config_renderer import ConfigRenderer
from agent_actions.response_processing.schema_loader import SchemaLoader
from agent_actions.services import WorkflowSchemaService
from agent_actions.validation.static_analyzer import FieldFlowAnalyzer


class FieldFlowCommand:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Implementation of the field-flow inspection command."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        verbose: bool,
        errors_only: bool,
        field_filter: Optional[str],
    ):
        """
        Initialize the field-flow command.

        Args:
            agent: Agent/workflow configuration name, optionally with action
                   (e.g., "my_workflow" or "my_workflow.extract_facts")
            user_code: Optional path to user code directory containing UDFs
            json_output: Whether to output as JSON
            verbose: Whether to show detailed information
            errors_only: Whether to show only validation errors
            field_filter: Optional field to trace (e.g., "extractor.summary")
        """
        # Parse workflow.action format
        self.action_filter: Optional[str] = None
        if "." in agent:
            parts = agent.split(".", 1)
            self.agent = parts[0]
            self.action_filter = parts[1]
        else:
            self.agent = agent

        self.agent_name = Path(self.agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.verbose = verbose
        self.errors_only = errors_only
        self.field_filter = field_filter
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
        """Execute the field-flow command."""
        if not self.json_output:
            if self.action_filter:
                self.console.print(
                    f"[cyan]Field Flow Analysis: {self.agent_name}.{self.action_filter}[/cyan]\n"
                )
            else:
                self.console.print(f"[cyan]Field Flow Analysis: {self.agent_name}[/cyan]\n")

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

        # Get UDF registry
        udf_registry: Dict[str, Any] = {}
        try:
            # pylint: disable=import-outside-toplevel
            from agent_actions.utilities.udf_management.udf_registry import UDF_REGISTRY

            udf_registry = UDF_REGISTRY
        except ImportError:
            pass

        # Create schema loader
        schema_loader = SchemaLoader()

        # Create service using unified approach
        service = WorkflowSchemaService(
            workflow_config,
            udf_registry=udf_registry,
            schema_loader=schema_loader,
            project_root=paths.current_dir,
            schema_dir=paths.schema_dir,
        )

        # Run validation
        result = service.validate()

        # Create field flow analyzer for lineage tracking
        flow_analyzer = FieldFlowAnalyzer(service.graph, result, self.agent_name)

        # Output based on format
        if self.json_output:
            self._output_json(flow_analyzer, service)
        else:
            self._output_rich(flow_analyzer, service, result, workflow.execution_order)

    def _output_json(
        self, flow_analyzer: FieldFlowAnalyzer, service: WorkflowSchemaService
    ) -> None:
        """Output as JSON."""
        if self.action_filter:
            schema = service.get_action_schema(self.action_filter)
            if schema:
                output = {
                    "workflow": self.agent_name,
                    "action": self.action_filter,
                    "action_info": schema.to_dict(),
                    "validation": flow_analyzer.validation_result.to_dict(),
                }
            else:
                schemas = service.get_all_schemas()
                available = list(schemas.keys())
                output = {
                    "workflow": self.agent_name,
                    "action": self.action_filter,
                    "error": f"Action '{self.action_filter}' not found",
                    "available_actions": available,
                    "validation": flow_analyzer.validation_result.to_dict(),
                }
        elif self.field_filter:
            lineage = flow_analyzer.filter_to_field(self.field_filter)
            if lineage:
                output = {
                    "workflow": self.agent_name,
                    "field": self.field_filter,
                    "lineage": lineage.to_dict(),
                    "validation": flow_analyzer.validation_result.to_dict(),
                }
            else:
                output = {
                    "workflow": self.agent_name,
                    "field": self.field_filter,
                    "error": f"Field '{self.field_filter}' not found",
                    "validation": flow_analyzer.validation_result.to_dict(),
                }
        else:
            output = service.to_dict()

        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(
        self,
        flow_analyzer: FieldFlowAnalyzer,
        service: WorkflowSchemaService,
        result,
        execution_order: list,
    ) -> None:
        """Output using rich formatting."""
        # Show validation status
        if result.is_valid:
            self.console.print("[green]All field references are valid[/green]\n")
        else:
            error_count = len(result.errors)
            warning_count = len(result.warnings)
            self.console.print(
                f"[red]{error_count} error(s), {warning_count} warning(s) found[/red]\n"
            )

        # If filtering to a specific action
        if self.action_filter:
            self._render_action_detail(service, result)
            return

        # If filtering to a specific field
        if self.field_filter:
            self._render_field_lineage_detail(flow_analyzer)
            return

        # If errors-only mode
        if self.errors_only:
            self._render_errors(result)
            return

        # Render flow visualization using service and renderer
        schemas = service.get_all_schemas()
        tree = self.renderer.render_flow_tree(schemas, execution_order, verbose=self.verbose)
        self.console.print(Panel(tree, title="Workflow Data Flow"))

        # Show field lineages if verbose
        if self.verbose:
            self._render_field_lineages(flow_analyzer)

        # Always show errors if any
        if not result.is_valid:
            self._render_errors(result)

    def _render_action_detail(self, service: WorkflowSchemaService, result) -> None:
        """Render detailed view for a specific action."""
        schema = service.get_action_schema(self.action_filter)

        if not schema:
            self.console.print(f"[red]Action '{self.action_filter}' not found[/red]")
            # Show available actions
            schemas = service.get_all_schemas()
            available = list(schemas.keys())
            if available:
                self.console.print(f"[dim]Available actions: {', '.join(available)}[/dim]")
            return

        # Use the unified renderer for action detail
        panel = self.renderer.render_action_detail(schema)
        self.console.print(panel)

        # Show any errors/warnings specific to this action
        action_errors = [e for e in result.errors if e.location.agent_name == self.action_filter]
        action_warnings = [
            w for w in result.warnings if w.location.agent_name == self.action_filter
        ]

        if action_errors:
            self.console.print("\n[bold red]Errors for this action:[/bold red]")
            for error in action_errors:
                self.console.print(f"  [red]•[/red] {error.message}")
                if error.hint:
                    self.console.print(f"    [yellow]Hint: {error.hint}[/yellow]")

        if action_warnings:
            self.console.print("\n[bold yellow]Warnings for this action:[/bold yellow]")
            for warning in action_warnings:
                self.console.print(f"  [yellow]•[/yellow] {warning.message}")
                if warning.hint:
                    self.console.print(f"    [dim]Hint: {warning.hint}[/dim]")

    def _render_field_lineages(self, flow_analyzer: FieldFlowAnalyzer) -> None:
        """Render detailed field lineages."""
        self.console.print("\n")

        flow = flow_analyzer.get_full_flow()

        if not flow.field_lineages:
            self.console.print("[dim]No field lineages to display[/dim]")
            return

        table = Table(title="Field Lineage", show_lines=True)
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Type", style="magenta", width=12)
        table.add_column("Consumers", style="green")
        table.add_column("Status", style="yellow", width=10)

        for field_key, lineage in sorted(flow.field_lineages.items()):
            consumers_str = ", ".join(f"{c.agent}" for c in lineage.consumers) or "[dim]none[/dim]"
            status = "[red]dropped[/red]" if lineage.is_dropped else "[green]active[/green]"
            table.add_row(field_key, lineage.field_type, consumers_str, status)

        self.console.print(table)

    def _render_field_lineage_detail(self, flow_analyzer: FieldFlowAnalyzer) -> None:
        """Render detailed lineage for a specific field."""
        lineage = flow_analyzer.filter_to_field(self.field_filter)

        if not lineage:
            self.console.print(f"[red]Field '{self.field_filter}' not found[/red]")
            return

        tree = Tree(f"[bold]Field Lineage: {self.field_filter}[/bold]")

        # Producer info
        producer_branch = tree.add(f"[cyan]Producer:[/cyan] {lineage.producer}")
        producer_branch.add(f"Type: {lineage.field_type}")
        if lineage.is_dropped:
            producer_branch.add("[red]Status: DROPPED[/red]")

        # Consumers
        if lineage.consumers:
            consumers_branch = tree.add("[green]Consumers:[/green]")
            for consumer in lineage.consumers:
                consumer_node = consumers_branch.add(f"[bold]{consumer.agent}[/bold]")
                consumer_node.add(f"Location: {consumer.location}")
                if self.verbose:
                    consumer_node.add(f"Reference: {consumer.raw_reference}")
        else:
            tree.add("[dim]No consumers[/dim]")

        self.console.print(Panel(tree))

    def _render_errors(self, result) -> None:
        """Render validation errors."""
        self.console.print("\n")

        if result.errors:
            self.console.print("[bold red]Errors:[/bold red]")
            for i, error in enumerate(result.errors, 1):
                self.console.print(f"\n[red]Error {i}:[/red]")
                self.console.print(f"  Action: {error.location.agent_name}")
                self.console.print(f"  Reference: {error.location.raw_reference}")
                self.console.print(f"  Location: {error.location.config_field}")
                self.console.print(f"  Problem: {error.message}")
                if error.available_fields:
                    fields_str = ", ".join(sorted(error.available_fields))
                    self.console.print(f"  Available: {fields_str}")
                if error.hint:
                    self.console.print(f"  [yellow]Hint: {error.hint}[/yellow]")

        if result.warnings:
            self.console.print("\n[bold yellow]Warnings:[/bold yellow]")
            for i, warning in enumerate(result.warnings, 1):
                self.console.print(f"\n[yellow]Warning {i}:[/yellow]")
                self.console.print(f"  Action: {warning.location.agent_name}")
                self.console.print(f"  {warning.message}")
                if warning.hint:
                    self.console.print(f"  [dim]Hint: {warning.hint}[/dim]")


@click.group(name="inspect")
def inspect():
    """Inspect workflow structure and data flow."""


@inspect.command(name="field-flow")
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Workflow name, optionally with action (e.g., 'my_workflow.action')",
)
@click.option(
    "-u",
    "--user-code",
    required=False,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to user code directory containing UDFs",
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
    help="Show detailed field lineage information",
)
@click.option(
    "--errors-only",
    is_flag=True,
    help="Show only validation errors",
)
@click.option(
    "--field",
    "field_filter",
    required=False,
    help="Trace a specific field (e.g., 'extractor.summary')",
)
@handles_user_errors("inspect field-flow")
@requires_project
def field_flow(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    agent: str,
    user_code: Optional[str],
    json_output: bool,
    verbose: bool,
    errors_only: bool,
    field_filter: Optional[str],
) -> None:
    """
    Trace and visualize data flow through a workflow.

    Analyzes how fields flow between actions, validates all field references,
    and shows clear errors with suggestions for typos.

    The -a/--agent option accepts either:
    - Workflow only: 'my_workflow' - shows entire workflow flow
    - Workflow.action: 'my_workflow.extract_facts' - shows detailed view of specific action

    Examples:
        # Whole workflow flow
        agac inspect field-flow -a my_workflow

        # Single action detail
        agac inspect field-flow -a my_workflow.extract_facts

        # JSON output
        agac inspect field-flow -a my_workflow --json
        agac inspect field-flow -a my_workflow.extract_facts --json

        # Trace specific field
        agac inspect field-flow -a my_workflow --field extractor.summary

        # Show only errors
        agac inspect field-flow -a my_workflow --errors-only

        # Verbose with field lineages
        agac inspect field-flow -a my_workflow --verbose
    """
    command = FieldFlowCommand(
        agent=agent,
        user_code=user_code,
        json_output=json_output,
        verbose=verbose,
        errors_only=errors_only,
        field_filter=field_filter,
    )
    command.execute()
