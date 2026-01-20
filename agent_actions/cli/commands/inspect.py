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
from agent_actions.errors import FileLoadError
from agent_actions.workflow.coordinator import AgentWorkflow, WorkflowConfig, WorkflowPaths
from agent_actions.prompt.renderer import ConfigRenderer


class BaseInspectCommand:
    """Base class for inspect commands with common functionality."""

    def __init__(self, agent: str, user_code: Optional[str], json_output: bool):
        """Initialize base command."""
        self.agent = agent
        self.agent_name = Path(agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.console = Console()
        self.paths = None  # Will be set by _load_workflow

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

    def _load_workflow(self) -> AgentWorkflow:
        """Load workflow configuration and store paths."""
        self.paths = ProjectPathsFactory.create_project_paths(self.agent_name, self.agent)
        filename = f"{self.agent_name}.yml"
        full_path = self._find_config_file(self.paths.agent_config_dir, filename)

        # Render configuration
        ConfigRenderer.render_and_load_config(
            self.agent_name, full_path, self.paths.template_dir, self.paths.rendered_workflows_dir
        )

        # Load workflow
        workflow = AgentWorkflow(
            WorkflowConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.user_code) if self.user_code else None,
                    default_path=str(self.paths.default_config_path),
                ),
                use_tools=False,
            )
        )
        return workflow


@click.group(name="inspect")
def inspect():
    """Inspect workflow structure and data flow."""


class DependenciesCommand(BaseInspectCommand):
    """Implementation of the dependencies inspection command."""

    def __init__(
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        action_filter: Optional[str],
    ):
        """Initialize the dependencies command."""
        super().__init__(agent, user_code, json_output)
        self.action_filter = action_filter

    def execute(self) -> None:
        """Execute the dependencies command."""
        if not self.json_output:
            self.console.print(f"[cyan]Dependency Analysis: {self.agent_name}[/cyan]\n")

        # Load workflow
        workflow = self._load_workflow()

        # Analyze dependencies
        dependency_info = self._analyze_dependencies(workflow)

        # Output based on format
        if self.json_output:
            self._output_json(dependency_info)
        else:
            self._output_rich(dependency_info, workflow.execution_order)

    def _analyze_dependencies(self, workflow: AgentWorkflow) -> Dict[str, Any]:
        """Analyze dependencies for all actions."""
        from agent_actions.prompt.context.scope import (
            ContextScopeProcessor,
        )

        workflow_actions = list(workflow.agent_configs.keys())
        result = {}

        for action_name, action_config in workflow.agent_configs.items():
            # Get explicit dependencies
            deps_raw = action_config.get("dependencies", [])
            if isinstance(deps_raw, str):
                explicit_deps = [deps_raw]
            elif isinstance(deps_raw, list):
                explicit_deps = deps_raw
            else:
                explicit_deps = []

            # Infer dependencies using the same logic as runtime
            try:
                input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
                    action_config, workflow_actions, action_name
                )
            except Exception as e:
                input_sources = explicit_deps
                context_sources = []

            # Get context_scope details
            context_scope = action_config.get("context_scope", {})
            observe = context_scope.get("observe", [])
            passthrough = context_scope.get("passthrough", [])

            # Check for deprecated primary_dependency
            has_primary_dep = "primary_dependency" in action_config
            primary_dep = action_config.get("primary_dependency") if has_primary_dep else None

            result[action_name] = {
                "explicit_dependencies": explicit_deps,
                "input_sources": input_sources,
                "context_sources": context_sources,
                "context_scope": {
                    "observe": observe,
                    "passthrough": passthrough,
                },
                "has_primary_dependency": has_primary_dep,
                "primary_dependency": primary_dep,
            }

        return result

    def _output_json(self, dependency_info: Dict[str, Any]) -> None:
        """Output dependencies as JSON."""
        output = {
            "workflow": self.agent_name,
            "actions": dependency_info,
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, dependency_info: Dict[str, Any], execution_order: list) -> None:
        """Output dependencies using rich formatting."""
        # Filter to specific action if requested
        if self.action_filter:
            if self.action_filter not in dependency_info:
                self.console.print(f"[red]Action '{self.action_filter}' not found[/red]")
                available = list(dependency_info.keys())
                self.console.print(f"[dim]Available actions: {', '.join(available)}[/dim]")
                return
            dependency_info = {self.action_filter: dependency_info[self.action_filter]}

        # Check for deprecated primary_dependency usage
        deprecated_actions = [
            name for name, info in dependency_info.items() if info["has_primary_dependency"]
        ]
        if deprecated_actions:
            self.console.print(
                "[yellow]⚠️  DEPRECATION WARNING: The following actions use 'primary_dependency':[/yellow]"
            )
            for name in deprecated_actions:
                self.console.print(f"  • {name}")
            self.console.print(
                "[dim]Use 'dependencies' for input sources; context is auto-inferred from context_scope[/dim]\n"
            )

        # Create table
        table = Table(title="Dependency Model", show_lines=True, title_style="bold cyan")
        table.add_column("Action", style="bold white", no_wrap=True)
        table.add_column("Input Sources", style="green")
        table.add_column("Context Sources", style="yellow")
        table.add_column("Type", style="cyan", width=12)

        # Sort by execution order if available
        actions_to_display = execution_order if execution_order else list(dependency_info.keys())

        for action_name in actions_to_display:
            if action_name not in dependency_info:
                continue

            info = dependency_info[action_name]
            input_sources = info["input_sources"]
            context_sources = info["context_sources"]

            # Format input sources
            if not input_sources:
                input_str = "[dim]none (source data)[/dim]"
                dep_type = "Source"
            elif len(input_sources) == 1:
                input_str = input_sources[0]
                dep_type = "Single Input"
            else:
                input_str = "\n".join(f"• {src}" for src in input_sources)
                dep_type = "Merge"

            # Format context sources
            if not context_sources:
                context_str = "[dim]none[/dim]"
            else:
                context_str = "\n".join(f"• {src} (auto)" for src in context_sources)

            table.add_row(action_name, input_str, context_str, dep_type)

        self.console.print(table)

        # Show detailed breakdown if single action
        if self.action_filter and self.action_filter in dependency_info:
            self._show_action_detail(self.action_filter, dependency_info[self.action_filter])

    def _show_action_detail(self, action_name: str, info: Dict[str, Any]) -> None:
        """Show detailed dependency info for a single action."""
        self.console.print(f"\n[bold]Detailed Dependency Info: {action_name}[/bold]\n")

        tree = Tree(f"[cyan]{action_name}[/cyan]")

        # Input sources
        if info["input_sources"]:
            input_branch = tree.add(
                "[bold green]Input Sources[/bold green] (execution dependencies)"
            )
            for src in info["input_sources"]:
                input_branch.add(f"• {src}")
            input_branch.add("[dim]→ Determines execution count (one run per input record)[/dim]")
        else:
            tree.add(
                "[bold green]Input Sources[/bold green]: [dim]none (processes source data)[/dim]"
            )

        # Context sources
        if info["context_sources"]:
            context_branch = tree.add(
                "[bold yellow]Context Sources[/bold yellow] (auto-inferred from context_scope)"
            )
            for src in info["context_sources"]:
                context_branch.add(f"• {src}")
            context_branch.add("[dim]→ Loaded via historical lineage (same branch as input)[/dim]")
        else:
            tree.add("[bold yellow]Context Sources[/bold yellow]: [dim]none[/dim]")

        # Context scope details
        context_scope = info["context_scope"]
        if context_scope["observe"] or context_scope["passthrough"]:
            scope_branch = tree.add("[bold]Context Scope Configuration[/bold]")
            if context_scope["observe"]:
                obs_branch = scope_branch.add("observe:")
                for field in context_scope["observe"]:
                    obs_branch.add(f"• {field}")
            if context_scope["passthrough"]:
                pass_branch = scope_branch.add("passthrough:")
                for field in context_scope["passthrough"]:
                    pass_branch.add(f"• {field}")

        # Deprecation warning
        if info["has_primary_dependency"]:
            tree.add(
                f"[yellow]⚠️  Uses deprecated 'primary_dependency': {info['primary_dependency']}[/yellow]"
            )

        self.console.print(Panel(tree))


@inspect.command(name="dependencies")
@click.option(
    "-a",
    "--agent",
    required=True,
    help="Agent/workflow configuration name",
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
    "--action",
    "action_filter",
    required=False,
    help="Show detailed view for a specific action",
)
@handles_user_errors("inspect dependencies")
@requires_project
def dependencies(
    agent: str,
    user_code: Optional[str],
    json_output: bool,
    action_filter: Optional[str],
) -> None:
    """
    Analyze workflow dependencies and auto-inferred context.

    Shows the simplified dependency model:
    - Input sources: Actions in 'dependencies' (determines execution count)
    - Context sources: Auto-inferred from 'context_scope' (historical data)

    This command validates the new dependency model and identifies:
    - Deprecated 'primary_dependency' usage
    - Auto-inferred context dependencies
    - Merge patterns (multiple input sources)

    Examples:
        # Analyze entire workflow
        agac inspect dependencies -a my_workflow

        # Detailed view for specific action
        agac inspect dependencies -a my_workflow --action generate_question

        # JSON output
        agac inspect dependencies -a my_workflow --json
    """
    command = DependenciesCommand(
        agent=agent,
        user_code=user_code,
        json_output=json_output,
        action_filter=action_filter,
    )
    command.execute()
