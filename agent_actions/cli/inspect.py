"""
Inspect commands for the Agent Actions CLI.

This module provides implementation of the 'inspect' command group,
which includes signatures, field-flow, and conflicts inspection commands.
"""
import click
import json
from typing import Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from agent_actions.llm_invocation.realtime.config_handler import ConfigManager
from agent_actions.validation.inspect_validator import SignaturesCommandArgs, FieldFlowCommandArgs, ConflictsCommandArgs
from agent_actions.cli.cli_decorators import requires_project
from agent_actions.cli.project_paths_factory import ProjectPathsFactory
from pydantic import ValidationError

def _create_config_manager(agent_name: str) -> ConfigManager:
    """
    Create and initialize ConfigManager using ProjectPathsFactory.
    
    This shared function eliminates code duplication across all inspect commands.
    
    Args:
        agent_name: Name of the agent to inspect
        
    Returns:
        Configured ConfigManager instance
    """
    paths = ProjectPathsFactory.create_project_paths(agent_name, agent_name)
    workflow_path = paths.agent_config_dir / f'{agent_name}.yml'
    config_manager = ConfigManager(str(workflow_path), str(paths.default_config_path))
    config_manager.load_configs()
    config_manager.validate_agent_name()
    user_agents = config_manager.get_user_agents()
    config_manager.merge_agent_configs(user_agents)
    config_manager.determine_execution_order()
    return config_manager

class InspectSignaturesCommand:
    """Implementation of the signatures inspect command."""

    def __init__(self, args: SignaturesCommandArgs):
        """Initialize the signatures command."""
        self.args = args
        self.console = Console()

    def execute(self) -> None:
        """Execute the signatures command."""
        try:
            config_manager = self._load_config_manager()
            all_signatures = config_manager.get_all_signatures()
            if self.args.filter_agent:
                if self.args.filter_agent not in all_signatures:
                    self.console.print(f"[red]Agent '{self.args.filter_agent}' not found in workflow[/red]")
                    return
                all_signatures = {self.args.filter_agent: all_signatures[self.args.filter_agent]}
            if self.args.format == 'json':
                self._render_json(all_signatures)
            else:
                self._render_table(all_signatures)
        except Exception as e:
            self.console.print(f'[red]Error: {str(e)}[/red]')

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager using shared function."""
        return _create_config_manager(self.args.agent_name)

    def _render_json(self, signatures: Dict[str, Dict[str, Any]]) -> None:
        """Render signatures as JSON."""
        json_data = {}
        for agent_name, sig_data in signatures.items():
            if 'error' in sig_data:
                json_data[agent_name] = sig_data
            else:
                json_data[agent_name] = {'dependencies': sig_data['dependencies'], 'execution_order_index': sig_data['execution_order_index'], 'is_operational': sig_data['is_operational'], 'input_signature': {'dependencies': sig_data['input_signature'].dependencies, 'source_fields': sig_data['input_signature'].source_fields, 'loop_fields': sig_data['input_signature'].loop_fields, 'workflow_fields': sig_data['input_signature'].workflow_fields, 'all_fields': list(sig_data['input_signature'].get_all_fields())}, 'output_signature': {'schema_fields': sig_data['output_signature'].schema_fields, 'observe_fields': sig_data['output_signature'].observe_fields, 'dropped_fields': sig_data['output_signature'].dropped_fields, 'available_fields': list(sig_data['output_signature'].get_available_fields())}}
        print(json.dumps(json_data, indent=2))

    def _render_table(self, signatures: Dict[str, Dict[str, Any]]) -> None:
        """Render signatures as a table."""
        table = Table(title='Agent Signatures')
        table.add_column('Agent', style='cyan', no_wrap=True)
        table.add_column('Dependencies', style='yellow')
        table.add_column('Execution Order', justify='center', style='green')
        table.add_column('Input Fields', style='blue')
        table.add_column('Output Fields', style='magenta')
        table.add_column('Status', justify='center')
        for agent_name, sig_data in signatures.items():
            if 'error' in sig_data:
                table.add_row(agent_name, str(sig_data.get('dependencies', [])), str(sig_data.get('execution_order_index', -1)), '[red]Error[/red]', '[red]Error[/red]', '[red]Failed[/red]')
            else:
                input_fields = list(sig_data['input_signature'].get_all_fields())
                output_fields = list(sig_data['output_signature'].get_available_fields())
                deps_str = ', '.join(sig_data['dependencies']) if sig_data['dependencies'] else 'None'
                input_str = ', '.join(sorted(input_fields)) if input_fields else 'None'
                output_str = ', '.join(sorted(output_fields)) if output_fields else 'None'
                status = '[green]✓[/green]' if sig_data['is_operational'] else '[yellow]○[/yellow]'
                table.add_row(agent_name, deps_str, str(sig_data['execution_order_index']), input_str, output_str, status)
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
            config_manager = self._load_config_manager()
            validation = config_manager.validate_field_flow()
            if self.args.format == 'json':
                self._render_json(validation)
            else:
                self._render_table(validation)
        except Exception as e:
            self.console.print(f'[red]Error: {str(e)}[/red]')

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager using shared function."""
        return _create_config_manager(self.args.agent_name)

    def _render_json(self, validation: Dict[str, Any]) -> None:
        """Render field flow validation as JSON."""
        json_data = {'valid': validation['valid'], 'errors': validation['errors'], 'warnings': validation['warnings'], 'agent_validations': {}, 'field_flow_summary': {}}
        for agent_name, agent_val in validation['agent_validations'].items():
            json_data['agent_validations'][agent_name] = {'valid': agent_val['valid'], 'errors': agent_val['errors'], 'warnings': agent_val['warnings'], 'available_fields_before': list(agent_val.get('available_fields_before', set())), 'output_fields': list(agent_val.get('output_fields', set())), 'required_fields': list(agent_val.get('required_fields', set()))}
        for agent_name, fields in validation['field_flow_summary'].items():
            json_data['field_flow_summary'][agent_name] = list(fields)
        print(json.dumps(json_data, indent=2))

    def _render_table(self, validation: Dict[str, Any]) -> None:
        """Render field flow validation as a table."""
        overall_status = '[green]✓ Valid[/green]' if validation['valid'] else '[red]✗ Invalid[/red]'
        self.console.print(f'\n[bold]Field Flow Validation: {overall_status}[/bold]')
        if validation['errors']:
            self.console.print(f"\n[red]Errors ({len(validation['errors'])}):[/red]")
            for error in validation['errors']:
                self.console.print(f'  • {error}')
        if validation['warnings']:
            self.console.print(f"\n[yellow]Warnings ({len(validation['warnings'])}):[/yellow]")
            for warning in validation['warnings']:
                self.console.print(f'  • {warning}')
        table = Table(title='Agent Field Flow Analysis')
        table.add_column('Agent', style='cyan', no_wrap=True)
        table.add_column('Status', justify='center', style='green')
        table.add_column('Required Fields', style='blue')
        table.add_column('Provides Fields', style='magenta')
        table.add_column('Fields Available', style='yellow')
        for agent_name, agent_val in validation['agent_validations'].items():
            status = '[green]✓[/green]' if agent_val['valid'] else '[red]✗[/red]'
            required = ', '.join(sorted(agent_val.get('required_fields', set()))) or 'None'
            provides = ', '.join(sorted(agent_val.get('output_fields', set()))) or 'None'
            available_count = len(validation['field_flow_summary'].get(agent_name, set()))
            table.add_row(agent_name, status, required, provides, str(available_count))
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
            config_manager = self._load_config_manager()
            if self.args.filter_agent:
                conflicts = config_manager.detect_field_conflicts(self.args.filter_agent)
                conflicts_data = {self.args.filter_agent: conflicts}
            else:
                conflicts_data = {}
                for agent_name in config_manager.agent_configs.keys():
                    conflicts_data[agent_name] = config_manager.detect_field_conflicts(agent_name)
            if self.args.format == 'json':
                self._render_json(conflicts_data)
            else:
                self._render_table(conflicts_data)
        except Exception as e:
            self.console.print(f'[red]Error: {str(e)}[/red]')

    def _load_config_manager(self) -> ConfigManager:
        """Load and initialize ConfigManager using shared function."""
        return _create_config_manager(self.args.agent_name)

    def _render_json(self, conflicts_data: Dict[str, Dict[str, Any]]) -> None:
        """Render conflicts as JSON."""
        json_data = {}
        for agent_name, conflicts in conflicts_data.items():
            if 'error' in conflicts:
                json_data[agent_name] = conflicts
            else:
                json_data[agent_name] = {'conflicts': conflicts['conflicts'], 'agent_dependencies': conflicts['agent_dependencies'], 'all_available_fields': {}}
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
                table.add_column('Field Name', style='red', no_wrap=True)
                table.add_column('Conflicting Providers', style='yellow')
                table.add_column('Recommendation', style='green')
                for field_name, providers in conflicts['conflicts'].items():
                    providers_str = ', '.join(providers)
                    recommendation = f'Qualify field references: {{{providers[0]}.{field_name}}}'
                    table.add_row(field_name, providers_str, recommendation)
                self.console.print(table)
        if total_conflicts == 0:
            self.console.print('\n[green]✓ No field conflicts detected in the workflow![/green]')
        else:
            self.console.print(f"\n[yellow]Found {total_conflicts} field conflicts across {len([a for a, c in conflicts_data.items() if c.get('conflicts')])} agents[/yellow]")

@click.group()
def inspect():
    """Inspect agent workflows, signatures and field dependencies.
    
    All inspect commands use the -a/--agent flag to specify which agent's workflow to analyze."""
    pass

@inspect.command()
@click.option('-a', '--agent', 'agent_name', required=True, help='Agent name to inspect')
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json']), help='Output format (default: table)')
@click.option('--filter-agent', help='Show signatures for specific agent only')
@requires_project
def signatures(agent_name: str, output_format: str, filter_agent: Optional[str]) -> None:
    """
    [REMOVED] Signature inspection has been removed from agent-actions.

    This command is no longer available as signature validation was removed.
    {source.field} references still work without validation.
    """
    click.echo("❌ The 'inspect signatures' command has been removed.")
    click.echo("   Signature validation is no longer part of agent-actions.")
    click.echo("   {source.field} references still work without pre-validation.")
    raise click.Abort()

@inspect.command(name='field-flow')
@click.option('-a', '--agent', 'agent_name', required=True, help='Agent name to inspect')
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json']), help='Output format (default: table)')
@requires_project
def field_flow(agent_name: str, output_format: str) -> None:
    """
    [REMOVED] Field flow validation has been removed from agent-actions.

    This command is no longer available as signature validation was removed.
    Field references work without validation.
    """
    click.echo("❌ The 'inspect field-flow' command has been removed.")
    click.echo("   Field flow validation is no longer part of agent-actions.")
    click.echo("   Field references still work without pre-validation.")
    raise click.Abort()

@inspect.command()
@click.option('-a', '--agent', 'agent_name', required=True, help='Agent name to inspect')
@click.option('--filter-agent', help='Check conflicts for specific agent only')
@click.option('--format', 'output_format', default='table', type=click.Choice(['table', 'json']), help='Output format (default: table)')
@requires_project
def conflicts(agent_name: str, filter_agent: Optional[str], output_format: str) -> None:
    """
    [REMOVED] Field conflict detection has been removed from agent-actions.

    This command is no longer available as signature validation was removed.
    Field conflicts are not detected at config time.
    """
    click.echo("❌ The 'inspect conflicts' command has been removed.")
    click.echo("   Field conflict detection is no longer part of agent-actions.")
    click.echo("   Field name conflicts will not be detected at config time.")
    raise click.Abort()