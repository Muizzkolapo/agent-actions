"""Validate-udfs CLI command for checking UDF references without running workflows."""

import inspect
import textwrap
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.markup import escape

from agent_actions.config.manager import ConfigManager
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.errors import (
    ConfigurationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
    enrich_exception_context,
    get_error_detail,
)
from agent_actions.input.loaders.udf import (
    discover_udfs,
    validate_udf_references,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.errors import format_user_error
from agent_actions.logging.events import ValidationCompleteEvent, ValidationStartEvent
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES
from agent_actions.utils.udf_management.registry import (
    clear_registry,
    get_udf_metadata,
)
from agent_actions.validation.bus_namespace_validator import find_unknown_bus_namespaces
from agent_actions.validation.file_udf_contract_validator import find_file_udf_contract_warnings


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
            # Enrich for UX parity with config_pipeline / list_udfs.
            enrich_exception_context(
                e,
                pipeline_stage="validate_udfs",
                search_path=str(self.user_code.resolve()),
                requested_path=str(self.user_code),
            )
            return {
                "valid": False,
                "error": e,
                "error_type": "load_error",
            }
        config_manager = ConfigManager(str(config_path), str(paths.default_config_path))
        config_manager.load_configs()
        try:
            config_manager.validate_agent_name()
        except ConfigurationError as e:
            if "agent_name" not in e.context or "config_filename" not in e.context:
                raise
            return {
                "valid": False,
                "error": e,
                "error_type": "name_mismatch",
            }
        config = config_manager.user_config
        if config is None:
            config = {}
        try:
            validate_udf_references(config)
            impl_refs = self._count_impl_references(config)
        except FunctionNotFoundError as e:
            return {
                "valid": False,
                "error": e,
                "error_type": "not_found",
            }

        structural = self._run_structural_preflight()
        if structural is not None:
            return structural

        return {
            "valid": True,
            "registry": registry,
            "impl_refs": impl_refs,
            "action_names": self._extract_action_names(config),
        }

    def _run_structural_preflight(self) -> dict[str, Any] | None:
        """Run the same structural pass inspect/schema/run do. None if it passes.

        UDF references and structure are disjoint checks — a broken ``impl:``
        passes the structural pass, and a missing ``context_scope`` passes the
        UDF pass — so a command running only one is not a gate.

        Goes through WorkflowInspector rather than assembling the config here:
        these checks read the fully expanded action shape, and this command
        otherwise runs only two of the config pipeline's seven stages.
        """
        from agent_actions.services.workflow_inspector import WorkflowInspector

        try:
            WorkflowInspector(self.agent_name, user_code_path=str(self.user_code)).validate()
        except Exception as e:
            return {"valid": False, "error": e, "error_type": "structural"}
        return None

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
                elif error_type == "name_mismatch":
                    self._handle_name_mismatch_error(error)
                elif error_type == "structural":
                    self._handle_structural_error(error)
                raise click.exceptions.Exit(1)
            registry = result["registry"]
            impl_refs = result["impl_refs"]
            udf_warnings = find_file_udf_contract_warnings(registry, referenced=impl_refs)
            udf_warnings += self._find_bus_namespace_warnings(
                registry, impl_refs, result["action_names"]
            )
            fire_event(
                ValidationCompleteEvent(
                    target="UDFs",
                    validator="validate-udfs",
                    error_count=0,
                    warning_count=len(udf_warnings),
                )
            )
            self.console.print("[green]✅ All UDF references valid[/green]")
            self.console.print("[green]✅ No duplicate function names[/green]")
            self.console.print("\n[bold]Summary:[/bold]")
            self.console.print(f"  - {len(impl_refs)} Tools referenced in config")
            self.console.print(f"  - {len(registry)} Tools discovered and registered")
            self.console.print("  - All functions found\n")
            for warning in udf_warnings:
                # escape: warnings embed UDF-controlled literals (bus keys, return
                # annotations) that may contain Rich markup (e.g. "[/x]", "list[dict]"),
                # which would otherwise crash the console or drop text.
                self.console.print(f"[yellow]⚠ {escape(warning)}[/yellow]")
            if impl_refs:
                self.console.print("[bold]Referenced UDFs:[/bold]")
                for ref in sorted(impl_refs):
                    try:
                        udf_meta = get_udf_metadata(ref)
                        self.console.print(f"  • {ref} ([cyan]{udf_meta['file']}[/cyan])")
                    except FunctionNotFoundError:
                        self.console.print(f"  • {ref}")
        except click.exceptions.Exit:
            raise
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

    def _extract_action_names(self, config: dict) -> set[str]:
        """Return workflow action names from the raw config (list-of-dicts form)."""
        actions = config.get("actions", [])
        if not isinstance(actions, list):
            return set()
        return {
            a["name"] for a in actions if isinstance(a, dict) and isinstance(a.get("name"), str)
        }

    def _find_bus_namespace_warnings(
        self, registry: dict, impl_refs: set[str], action_names: set[str]
    ) -> list[str]:
        """Scan each REFERENCED UDF's own source for reads of an unknown bus namespace.

        Scoped to impl_refs, and to each UDF's own function body (not its whole file):
        a shared tools/ dir holds UDFs for many workflows — each reading its own
        workflow's action names — and a UDF file often defines record-level helpers
        that receive a plain record, not the action-keyed bus. Scanning either would
        flag legitimate reads against the wrong namespace set.
        """
        sources: dict[str, str] = {}
        for ref in impl_refs:
            meta = registry.get(ref) or registry.get(ref.lower())
            if meta is None:
                continue
            try:
                sources[ref] = textwrap.dedent(inspect.getsource(meta["function"]))
            except (OSError, TypeError, KeyError):
                continue
        return find_unknown_bus_namespaces(sources, action_names | RUNTIME_BUS_NAMESPACES)

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

    def _handle_name_mismatch_error(self, error: ConfigurationError) -> None:
        """Report a workflow whose name field does not equal its filename stem."""
        actual = error.context["agent_name"]
        expected = error.context["config_filename"]
        self.console.print(
            f"[red]❌ Error: workflow name '{actual}' does not match filename "
            f"'{expected}.yml'[/red]\n"
            f"  Rename the file to '{actual}.yml', or set 'name: {expected}' in the config."
        )

    def _handle_load_error(self, error: UDFLoadError) -> None:
        """Render via the shared translator chain so UX stays in sync with the CLI."""
        # markup=False: format_user_error returns plain text that can contain
        # brackets (e.g. [WinError 126]) which Rich would otherwise consume.
        self.console.print("[red]❌ UDF load failed[/red]\n")
        self.console.print(format_user_error(error), markup=False, highlight=False)
        self.console.print()

    def _handle_structural_error(self, error: Exception) -> None:
        """Surface a structural failure; exiting 1 in silence is not a gate."""
        from rich.markup import escape

        self.console.print("[red]❌ Workflow configuration is not valid[/red]\n")
        self.console.print(f"  {escape(get_error_detail(error))}\n")
        self.console.print(
            "  This is the same check [cyan]agac inspect[/cyan] runs; run it for the full report.\n"
        )

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
