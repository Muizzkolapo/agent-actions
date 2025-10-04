"""
validate-udfs command for the Agent Actions CLI.

This module provides the implementation of the 'validate-udfs' command,
which validates all UDF references in a config file without running the workflow.
"""

import click
from pathlib import Path
from typing import Set

from rich.console import Console

from agent_actions.core.udf_loader import discover_udfs, validate_udf_references
from agent_actions.core.udf_registry import clear_registry, UDF_REGISTRY
from agent_actions.tasks.services.project_paths_factory import ProjectPathsFactory
from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.core.exceptions import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError
)


class ValidateUDFsCommand:
    """Implementation of the validate-udfs command."""

    def __init__(self, agent: str, user_code: str):
        """
        Initialize the validate-udfs command.

        Args:
            agent: Agent configuration file name
            user_code: Path to user code directory containing UDFs
        """
        self.agent_name = Path(agent).stem
        self.agent_file = agent
        self.user_code = Path(user_code)
        self.console = Console()

    def execute(self) -> None:
        """Execute the validate-udfs command."""
        try:
            # Get project paths
            paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent_file)

            # Find config file
            filename = f"{self.agent_name}.yml"
            config_path = paths.agent_config_dir / filename

            if not config_path.exists():
                raise FileNotFoundError(f"Config file not found: {config_path}")

            # Clear registry to ensure fresh discovery
            clear_registry()

            # Step 1: Discover UDFs
            self.console.print("[cyan]🔍 Discovering UDFs...[/cyan]")
            try:
                registry = discover_udfs(self.user_code)
                self.console.print(f"[green]✅ Discovered {len(registry)} UDF(s)[/green]\n")
            except DuplicateFunctionError as e:
                self._handle_duplicate_error(e)
                return
            except UDFLoadError as e:
                self._handle_load_error(e)
                return

            # Step 2: Load config
            self.console.print("Loading configuration...")
            config_manager = ConfigManager(str(config_path), str(paths.default_config_path))
            config = config_manager.config

            # Step 3: Validate UDF references
            self.console.print("Validating UDF references in config...\n")
            try:
                validate_udf_references(config)

                # Count how many UDFs are referenced
                impl_refs = self._count_impl_references(config)

                # Success output
                self.console.print("[green]✅ All UDF references valid[/green]")
                self.console.print("[green]✅ No duplicate function names[/green]")

                self.console.print(f"\n[bold]Summary:[/bold]")
                self.console.print(f"  - {len(impl_refs)} UDF(s) referenced in config")
                self.console.print(f"  - {len(registry)} UDF(s) discovered and registered")
                self.console.print(f"  - All functions found\n")

                if impl_refs:
                    self.console.print("[bold]Referenced UDFs:[/bold]")
                    for ref in sorted(impl_refs):
                        udf_meta = UDF_REGISTRY.get(ref.lower())
                        if udf_meta:
                            self.console.print(f"  • {ref} ([cyan]{udf_meta['file']}[/cyan])")

            except FunctionNotFoundError as e:
                self._handle_not_found_error(e)
                return

        except Exception as e:
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {
                'command': 'validate-udfs',
                'agent': self.agent_name,
                'user_code': str(self.user_code)
            })
            raise click.ClickException(error_message)

    def _count_impl_references(self, config: dict) -> Set[str]:
        """
        Count unique impl references in config.

        Args:
            config: Configuration dictionary

        Returns:
            Set of unique impl reference names
        """
        impl_refs = set()

        def extract_impl_refs(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == 'impl' and isinstance(value, str):
                        impl_refs.add(value)
                    else:
                        extract_impl_refs(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_impl_refs(item)

        extract_impl_refs(config)
        return impl_refs

    def _handle_duplicate_error(self, error: DuplicateFunctionError) -> None:
        """Handle duplicate function error with formatted output."""
        self.console.print(f"[red]❌ Error: Duplicate function name '{error.context['function_name']}'[/red]\n")

        self.console.print("[bold]First definition:[/bold]")
        self.console.print(f"  Location: {error.context['existing_location']}")
        self.console.print(f"  File: [cyan]{error.context['existing_file']}[/cyan]\n")

        self.console.print("[bold]Duplicate definition:[/bold]")
        self.console.print(f"  Location: {error.context['new_location']}")
        self.console.print(f"  File: [cyan]{error.context['new_file']}[/cyan]\n")

        self.console.print("[yellow]Fix:[/yellow]")
        self.console.print("  Function names must be unique. Rename one of these functions.\n")

    def _handle_load_error(self, error: UDFLoadError) -> None:
        """Handle UDF load error with formatted output."""
        self.console.print(f"[red]❌ Error loading UDF module[/red]\n")

        self.console.print(f"  Module: {error.context.get('module', 'unknown')}")
        self.console.print(f"  File: [cyan]{error.context.get('file', 'unknown')}[/cyan]")
        self.console.print(f"  Error: {error.context.get('error', 'unknown')}\n")

        self.console.print("[yellow]Fix:[/yellow]")
        self.console.print("  Check the Python file for syntax errors or import issues.\n")

    def _handle_not_found_error(self, error: FunctionNotFoundError) -> None:
        """Handle function not found error with formatted output."""
        self.console.print(f"[red]❌ Function '{error.context['function_name']}' not found[/red]\n")

        self.console.print("  This function is referenced in your config but not registered.")
        self.console.print("  Did you forget the @udf_tool decorator?\n")

        available = error.context.get('available_functions', [])
        if available:
            self.console.print(f"[bold]Available functions ({len(available)}):[/bold]")
            for func in available[:10]:  # Show first 10
                udf_meta = UDF_REGISTRY.get(func.lower())
                if udf_meta:
                    self.console.print(f"  • {func} ([cyan]{udf_meta['file']}[/cyan])")
            if len(available) > 10:
                self.console.print(f"  ... and {len(available) - 10} more\n")
            else:
                self.console.print()

        self.console.print("[yellow]Fix:[/yellow]")
        self.console.print("  1. Check the function name spelling")
        self.console.print("  2. Ensure the function has @udf_tool decorator")
        self.console.print("  3. Verify the file is in the user code directory\n")


@click.command(name='validate-udfs')
@click.option('-a', '--agent', required=True,
              help="Agent configuration file name without path or extension")
@click.option('-u', '--user-code', required=True,
              type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help="Path to user code directory containing UDFs")
def validate_udfs_cmd(agent: str, user_code: str) -> None:
    """
    Validate all UDF references in config without running the workflow.

    Discovers UDFs from the user code directory and verifies that all
    'impl' references in the agent configuration exist and are properly
    decorated with @udf_tool.
    """
    command = ValidateUDFsCommand(agent, user_code)
    command.execute()
