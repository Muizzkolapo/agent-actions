"""Validate-udfs CLI command for checking UDF references without running workflows."""

from pathlib import Path
from typing import Any

import click
from rich.console import Console

from agent_actions.config.manager import ConfigManager
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors import (
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
)
from agent_actions.input.loaders.udf import (
    discover_udfs,
    validate_udf_references,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.errors import format_user_error
from agent_actions.logging.events import ValidationCompleteEvent, ValidationStartEvent
from agent_actions.utils.udf_management.registry import (
    clear_registry,
    get_udf_metadata,
)


class ValidateUDFsCommand:
    """Implementation of the validate-udfs command."""

    def __init__(self, agent: str, user_code: str):
        """Initialize with agent config file name and user code directory path."""
        self.agent_name = Path(agent).stem
        self.agent_file = agent
        self.user_code = Path(user_code)
        self.console = Console()

    def validate(self) -> dict[str, Any]:
        """Perform UDF validation and return the result dict."""
        paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent_file)
        filename = f"{self.agent_name}.yml"
        config_path = paths.agent_config_dir / filename
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        clear_registry()
        try:
            registry = discover_udfs(self.user_code)
        except DuplicateFunctionError as e:
            return {
                "valid": False,
                "error": e,
                "error_type": "duplicate",
            }
        except UDFLoadError as e:
            return {
                "valid": False,
                "error": e,
                "error_type": "load_error",
            }
        config_manager = ConfigManager(str(config_path), str(paths.default_config_path))
        config_manager.load_configs()
        config = config_manager.user_config
        if config is None:
            config = {}
        try:
            validate_udf_references(config)
            impl_refs = self._count_impl_references(config)
            return {
                "valid": True,
                "registry": registry,
                "impl_refs": impl_refs,
            }
        except FunctionNotFoundError as e:
            return {
                "valid": False,
                "error": e,
                "error_type": "not_found",
            }

    def execute(self) -> None:
        """Execute the validate-udfs command with formatted CLI output."""
        try:
            fire_event(ValidationStartEvent(target="UDFs", validator="validate-udfs"))
            result = self.validate()
            if not result["valid"]:
                error = result["error"]
                error_type = result["error_type"]
                if error_type == "duplicate":
                    self._handle_duplicate_error(error)
                elif error_type == "load_error":
                    self._handle_load_error(error)
                elif error_type == "not_found":
                    self._handle_not_found_error(error)
                return
            registry = result["registry"]
            impl_refs = result["impl_refs"]
            fire_event(
                ValidationCompleteEvent(
                    target="UDFs", validator="validate-udfs", error_count=0, warning_count=0
                )
            )
            self.console.print("[green]✅ All UDF references valid[/green]")
            self.console.print("[green]✅ No duplicate function names[/green]")
            self.console.print("\n[bold]Summary:[/bold]")
            self.console.print(f"  - {len(impl_refs)} Tools referenced in config")
            self.console.print(f"  - {len(registry)} Tools discovered and registered")
            self.console.print("  - All functions found\n")
            if impl_refs:
                self.console.print("[bold]Referenced UDFs:[/bold]")
                for ref in sorted(impl_refs):
                    try:
                        udf_meta = get_udf_metadata(ref)
                        self.console.print(f"  • {ref} ([cyan]{udf_meta['file']}[/cyan])")
                    except FunctionNotFoundError:
                        self.console.print(f"  • {ref}")
        except Exception as e:
            error_message = format_user_error(
                e,
                {
                    "command": "validate-udfs",
                    "agent": self.agent_name,
                    "user_code": str(self.user_code),
                },
            )
            raise click.ClickException(error_message) from e

    def _count_impl_references(self, config: dict) -> set[str]:
        """Return set of unique impl reference names from config."""
        impl_refs = set()

        def extract_impl_refs(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "impl" and isinstance(value, str):
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
        func_name = error.context["function_name"]
        self.console.print(f"[red]❌ Error: Duplicate function name '{func_name}'[/red]\n")
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
        self.console.print("[red]❌ Error loading UDF module[/red]\n")
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
        available = error.context.get("available_functions", [])
        if available:
            self.console.print(f"[bold]Available functions ({len(available)}):[/bold]")
            for func in available[:10]:
                try:
                    udf_meta = get_udf_metadata(func)
                    self.console.print(f"  • {func} ([cyan]{udf_meta['file']}[/cyan])")
                except FunctionNotFoundError:
                    self.console.print(f"  • {func}")
            if len(available) > 10:
                self.console.print(f"  ... and {len(available) - 10} more\n")
            else:
                self.console.print()
        self.console.print("[yellow]Fix:[/yellow]")
        self.console.print("  1. Check the function name spelling")
        self.console.print("  2. Ensure the function has @udf_tool decorator")
        self.console.print("  3. Verify the file is in the user code directory\n")


@click.command(name="validate-udfs")
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent configuration file name without path or extension",
)
@click.option(
    "-u",
    "--user-code",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to user code directory containing UDFs",
)
def validate_udfs_cmd(agent: str, user_code: str) -> None:
    """Validate all UDF references in config without running the workflow."""
    command = ValidateUDFsCommand(agent, user_code)
    command.execute()
