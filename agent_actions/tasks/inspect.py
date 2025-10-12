"""
Inspect commands for the Agent Actions CLI.

This module provides implementation of the 'inspect' command group,
which includes signatures, field-flow, and conflicts inspection commands.
"""

import click
import json
from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.text import Text

from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.agents.validators.inspect_validator import (
    SignaturesCommandArgs,
    FieldFlowCommandArgs,
    ConflictsCommandArgs
)
from agent_actions.core.cli_decorators import requires_project
from agent_actions.core.exceptions import ConfigurationError
from pydantic import ValidationError


class InspectSignaturesCommand:
    """Implementation of the signatures inspect command."""

    def __init__(self, args: SignaturesCommandArgs):
        """Initialize the signatures command."""
        self.args = args
        self.console = Console()

    def execute(self) -> None:
        """Execute the signatures command."""
        try:
            # Load workflow configuration
            config_manager = self._load_config_manager()
            
            # Get all signatures
            all_signatures = config_manager.get_all_signatures()
            
            # Filter by agent if specified
            if self.args.agent:
                if self.args.agent not in all_signatures:
                    self.console.print(f"[red]Agent '{self.args.agent}' not found in workflow[/red]")
                    return
                all_signatures = {self.args.agent: all_signatures[self.args.agent]}
            
            # Render output
            if self.args.format == "json":
                self._render_json(all_signatures)
            else:
                self._render_table(all_signatures)
                
        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager."""
        # Look for defaults file in same directory as workflow
        defaults_path = Path(self.args.workflow_path).parent / "defaults.yml"
        if not defaults_path.exists():
            # Create minimal defaults if none exist
            defaults_path = Path(self.args.workflow_path).parent / "temp_defaults.yml"
            defaults_content = """default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-haiku-20240307
  api_key: fake-key-for-testing
  anthropic_version: "2023-06-01"
  max_tokens: 1000
  temperature: 0.1"""
            defaults_path.write_text(defaults_content)
        
        config_manager = ConfigManager(self.args.workflow_path, str(defaults_path))
        config_manager.load_configs()
        config_manager.validate_agent_name()
        
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order(user_agents)
        
        # Clean up temp file if we created it
        if defaults_path.name == "temp_defaults.yml":
            defaults_path.unlink(missing_ok=True)
        
        return config_manager

    def _render_json(self, signatures: Dict[str, Dict[str, Any]]) -> None:
        """Render signatures as JSON."""
        # Convert signature objects to dictionaries for JSON serialization
        json_data = {}
        for agent_name, sig_data in signatures.items():
            if 'error' in sig_data:
                json_data[agent_name] = sig_data
            else:
                json_data[agent_name] = {
                    'dependencies': sig_data['dependencies'],
                    'execution_order_index': sig_data['execution_order_index'],
                    'is_operational': sig_data['is_operational'],
                    'input_signature': {
                        'dependencies': sig_data['input_signature'].dependencies,
                        'source_fields': sig_data['input_signature'].source_fields,
                        'loop_fields': sig_data['input_signature'].loop_fields,
                        'workflow_fields': sig_data['input_signature'].workflow_fields,
                        'all_fields': list(sig_data['input_signature'].get_all_fields())
                    },
                    'output_signature': {
                        'schema_fields': sig_data['output_signature'].schema_fields,
                        'observe_fields': sig_data['output_signature'].observe_fields,
                        'dropped_fields': sig_data['output_signature'].dropped_fields,
                        'available_fields': list(sig_data['output_signature'].get_available_fields())
                    }
                }
        
        print(json.dumps(json_data, indent=2))

    def _render_table(self, signatures: Dict[str, Dict[str, Any]]) -> None:
        """Render signatures as a table."""
        table = Table(title="Agent Signatures")
        table.add_column("Agent", style="cyan", no_wrap=True)
        table.add_column("Dependencies", style="yellow")
        table.add_column("Execution Order", justify="center", style="green")
        table.add_column("Input Fields", style="blue")
        table.add_column("Output Fields", style="magenta")
        table.add_column("Status", justify="center")

        for agent_name, sig_data in signatures.items():
            if 'error' in sig_data:
                table.add_row(
                    agent_name,
                    str(sig_data.get('dependencies', [])),
                    str(sig_data.get('execution_order_index', -1)),
                    "[red]Error[/red]",
                    "[red]Error[/red]",
                    "[red]Failed[/red]"
                )
            else:
                input_fields = list(sig_data['input_signature'].get_all_fields())
                output_fields = list(sig_data['output_signature'].get_available_fields())
                
                deps_str = ", ".join(sig_data['dependencies']) if sig_data['dependencies'] else "None"
                input_str = ", ".join(sorted(input_fields)) if input_fields else "None"
                output_str = ", ".join(sorted(output_fields)) if output_fields else "None"
                
                status = "[green]✓[/green]" if sig_data['is_operational'] else "[yellow]○[/yellow]"
                
                table.add_row(
                    agent_name,
                    deps_str,
                    str(sig_data['execution_order_index']),
                    input_str,
                    output_str,
                    status
                )

        self.console.print(table)


class InspectFieldFlowCommand:
    """Implementation of the field-flow inspect command."""

    def __init__(self, args: FieldFlowCommandArgs):
        """Initialize the field-flow command."""
        self.args = args
        self.console = Console()

    def execute(self) -> None:
        """Execute the field-flow command."""
        try:
            # Load workflow configuration
            config_manager = self._load_config_manager()
            
            # Validate field flow
            validation = config_manager.validate_field_flow()
            
            # Render output
            if self.args.format == "json":
                self._render_json(validation)
            else:
                self._render_table(validation)
                
        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager."""
        # Look for defaults file in same directory as workflow
        defaults_path = Path(self.args.workflow_path).parent / "defaults.yml"
        if not defaults_path.exists():
            # Create minimal defaults if none exist
            defaults_path = Path(self.args.workflow_path).parent / "temp_defaults.yml"
            defaults_content = """default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-haiku-20240307
  api_key: fake-key-for-testing
  anthropic_version: "2023-06-01"
  max_tokens: 1000
  temperature: 0.1"""
            defaults_path.write_text(defaults_content)
        
        config_manager = ConfigManager(self.args.workflow_path, str(defaults_path))
        config_manager.load_configs()
        config_manager.validate_agent_name()
        
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order(user_agents)
        
        # Clean up temp file if we created it
        if defaults_path.name == "temp_defaults.yml":
            defaults_path.unlink(missing_ok=True)
        
        return config_manager

    def _render_json(self, validation: Dict[str, Any]) -> None:
        """Render field flow validation as JSON."""
        # Convert sets to lists for JSON serialization
        json_data = {
            'valid': validation['valid'],
            'errors': validation['errors'],
            'warnings': validation['warnings'],
            'agent_validations': {},
            'field_flow_summary': {}
        }
        
        for agent_name, agent_val in validation['agent_validations'].items():
            json_data['agent_validations'][agent_name] = {
                'valid': agent_val['valid'],
                'errors': agent_val['errors'],
                'warnings': agent_val['warnings'],
                'available_fields_before': list(agent_val.get('available_fields_before', set())),
                'output_fields': list(agent_val.get('output_fields', set())),
                'required_fields': list(agent_val.get('required_fields', set()))
            }
        
        for agent_name, fields in validation['field_flow_summary'].items():
            json_data['field_flow_summary'][agent_name] = list(fields)
        
        print(json.dumps(json_data, indent=2))

    def _render_table(self, validation: Dict[str, Any]) -> None:
        """Render field flow validation as a table."""
        # Overall status
        overall_status = "[green]✓ Valid[/green]" if validation['valid'] else "[red]✗ Invalid[/red]"
        self.console.print(f"\n[bold]Field Flow Validation: {overall_status}[/bold]")
        
        if validation['errors']:
            self.console.print(f"\n[red]Errors ({len(validation['errors'])}):[/red]")
            for error in validation['errors']:
                self.console.print(f"  • {error}")
        
        if validation['warnings']:
            self.console.print(f"\n[yellow]Warnings ({len(validation['warnings'])}):[/yellow]")
            for warning in validation['warnings']:
                self.console.print(f"  • {warning}")
        
        # Agent validation table
        table = Table(title="Agent Field Flow Analysis")
        table.add_column("Agent", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center", style="green")
        table.add_column("Required Fields", style="blue")
        table.add_column("Provides Fields", style="magenta")
        table.add_column("Fields Available", style="yellow")
        
        for agent_name, agent_val in validation['agent_validations'].items():
            status = "[green]✓[/green]" if agent_val['valid'] else "[red]✗[/red]"
            required = ", ".join(sorted(agent_val.get('required_fields', set()))) or "None"
            provides = ", ".join(sorted(agent_val.get('output_fields', set()))) or "None"
            
            # Get available fields count from field flow summary
            available_count = len(validation['field_flow_summary'].get(agent_name, set()))
            
            table.add_row(
                agent_name,
                status,
                required,
                provides,
                str(available_count)
            )
        
        self.console.print(table)


class InspectConflictsCommand:
    """Implementation of the conflicts inspect command."""

    def __init__(self, args: ConflictsCommandArgs):
        """Initialize the conflicts command."""
        self.args = args
        self.console = Console()

    def execute(self) -> None:
        """Execute the conflicts command."""
        try:
            # Load workflow configuration
            config_manager = self._load_config_manager()
            
            if self.args.agent_name:
                # Check specific agent
                conflicts = config_manager.detect_field_conflicts(self.args.agent_name)
                conflicts_data = {self.args.agent_name: conflicts}
            else:
                # Check all agents
                conflicts_data = {}
                for agent_name in config_manager.agent_configs.keys():
                    conflicts_data[agent_name] = config_manager.detect_field_conflicts(agent_name)
            
            # Render output
            if self.args.format == "json":
                self._render_json(conflicts_data)
            else:
                self._render_table(conflicts_data)
                
        except Exception as e:
            self.console.print(f"[red]Error: {str(e)}[/red]")

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager."""
        # Look for defaults file in same directory as workflow
        defaults_path = Path(self.args.workflow_path).parent / "defaults.yml"
        if not defaults_path.exists():
            # Create minimal defaults if none exist
            defaults_path = Path(self.args.workflow_path).parent / "temp_defaults.yml"
            defaults_content = """default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-haiku-20240307
  api_key: fake-key-for-testing
  anthropic_version: "2023-06-01"
  max_tokens: 1000
  temperature: 0.1"""
            defaults_path.write_text(defaults_content)
        
        config_manager = ConfigManager(self.args.workflow_path, str(defaults_path))
        config_manager.load_configs()
        config_manager.validate_agent_name()
        
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order(user_agents)
        
        # Clean up temp file if we created it
        if defaults_path.name == "temp_defaults.yml":
            defaults_path.unlink(missing_ok=True)
        
        return config_manager

    def _render_json(self, conflicts_data: Dict[str, Dict[str, Any]]) -> None:
        """Render conflicts as JSON."""
        # Convert sets to lists for JSON serialization
        json_data = {}
        for agent_name, conflicts in conflicts_data.items():
            if 'error' in conflicts:
                json_data[agent_name] = conflicts
            else:
                json_data[agent_name] = {
                    'conflicts': conflicts['conflicts'],
                    'agent_dependencies': conflicts['agent_dependencies'],
                    'all_available_fields': {}
                }
                
                for dep_name, fields in conflicts['all_available_fields'].items():
                    if isinstance(fields, set):
                        json_data[agent_name]['all_available_fields'][dep_name] = list(fields)
                    else:
                        json_data[agent_name]['all_available_fields'][dep_name] = fields
        
        print(json.dumps(json_data, indent=2))

    def _render_table(self, conflicts_data: Dict[str, Dict[str, Any]]) -> None:
        """Render conflicts as a table."""
        total_conflicts = 0
        
        for agent_name, conflicts in conflicts_data.items():
            if 'error' in conflicts:
                self.console.print(f"\n[red]Error for agent '{agent_name}': {conflicts['error']}[/red]")
                continue
            
            if conflicts['conflicts']:
                total_conflicts += len(conflicts['conflicts'])
                
                self.console.print(f"\n[bold]Conflicts for agent '{agent_name}':[/bold]")
                
                table = Table()
                table.add_column("Field Name", style="red", no_wrap=True)
                table.add_column("Conflicting Providers", style="yellow")
                table.add_column("Recommendation", style="green")
                
                for field_name, providers in conflicts['conflicts'].items():
                    providers_str = ", ".join(providers)
                    recommendation = f"Qualify field references: {{{providers[0]}.{field_name}}}"
                    table.add_row(field_name, providers_str, recommendation)
                
                self.console.print(table)
        
        if total_conflicts == 0:
            self.console.print("\n[green]✓ No field conflicts detected in the workflow![/green]")
        else:
            self.console.print(f"\n[yellow]Found {total_conflicts} field conflicts across {len([a for a, c in conflicts_data.items() if c.get('conflicts')])} agents[/yellow]")


# Click command group and individual commands
@click.group()
def inspect():
    """Inspect workflow signatures and field dependencies."""
    pass


@inspect.command()
@click.argument('workflow_path', type=click.Path(exists=True))
@click.option('--format', 'output_format', default='table', 
              type=click.Choice(['table', 'json']),
              help='Output format (default: table)')
@click.option('--agent', help='Show signatures for specific agent only')
def signatures(workflow_path: str, output_format: str, agent: Optional[str]) -> None:
    """
    Display input and output signatures for workflow agents.
    
    Shows the field dependencies and outputs for each agent in the workflow,
    helping to understand data flow between agents.
    """
    try:
        args = SignaturesCommandArgs(
            workflow_path=workflow_path,
            format=output_format,
            agent=agent
        )
        command = InspectSignaturesCommand(args)
        command.execute()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'inspect signatures'})
        raise click.ClickException(error_message)


@inspect.command(name='field-flow')
@click.argument('workflow_path', type=click.Path(exists=True))
@click.option('--format', 'output_format', default='table',
              type=click.Choice(['table', 'json']),
              help='Output format (default: table)')
def field_flow(workflow_path: str, output_format: str) -> None:
    """
    Validate field flow through the entire workflow.
    
    Analyzes field dependencies across all agents to detect missing fields,
    validate references, and ensure proper data flow through the workflow.
    """
    try:
        args = FieldFlowCommandArgs(
            workflow_path=workflow_path,
            format=output_format
        )
        command = InspectFieldFlowCommand(args)
        command.execute()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'inspect field-flow'})
        raise click.ClickException(error_message)


@inspect.command()
@click.argument('workflow_path', type=click.Path(exists=True))
@click.argument('agent_name', required=False)
@click.option('--format', 'output_format', default='table',
              type=click.Choice(['table', 'json']),
              help='Output format (default: table)')
def conflicts(workflow_path: str, agent_name: Optional[str], output_format: str) -> None:
    """
    Detect field name conflicts between dependency agents.
    
    Identifies cases where multiple dependency agents provide fields with
    the same name, which could cause ambiguity in field references.
    """
    try:
        args = ConflictsCommandArgs(
            workflow_path=workflow_path,
            agent_name=agent_name,
            format=output_format
        )
        command = InspectConflictsCommand(args)
        command.execute()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'inspect conflicts'})
        raise click.ClickException(error_message)