"""
Inspect commands for the Agent Actions CLI.

This module provides the implementation of the 'inspect' command group,
which includes subcommands for analyzing workflow structure and data flow.
"""

import json as json_lib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger(__name__)


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

    def _analyze_dependencies(self, workflow: AgentWorkflow) -> Dict[str, Any]:
        """Analyze dependencies for all actions using runtime inference logic."""
        from agent_actions.prompt.context.scope import ContextScopeProcessor

        workflow_actions = list(workflow.agent_configs.keys())
        result = {}

        for action_name, action_config in workflow.agent_configs.items():
            deps_raw = action_config.get("dependencies", [])
            if isinstance(deps_raw, str):
                explicit_deps = [deps_raw]
            elif isinstance(deps_raw, list):
                explicit_deps = deps_raw
            else:
                explicit_deps = []

            try:
                input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
                    action_config, workflow_actions, action_name
                )
            except Exception as e:
                # Fall back to explicit deps if inference fails
                if not self.json_output:
                    self.console.print(
                        f"[dim]Warning: Could not infer dependencies for {action_name}: {e}[/dim]"
                    )
                input_sources = explicit_deps
                context_sources = []

            context_scope = action_config.get("context_scope", {})
            has_primary_dep = "primary_dependency" in action_config

            result[action_name] = {
                "explicit_dependencies": explicit_deps,
                "input_sources": input_sources,
                "context_sources": context_sources,
                "context_scope": {
                    "observe": context_scope.get("observe", []),
                    "passthrough": context_scope.get("passthrough", []),
                },
                "has_primary_dependency": has_primary_dep,
                "primary_dependency": action_config.get("primary_dependency"),
            }

        return result

    @staticmethod
    def _get_action_type(input_sources: List[str], context_sources: List[str]) -> str:
        """Describe the action type based on its dependencies."""
        if not input_sources:
            return "Source"
        if len(input_sources) > 1:
            return "Merge" if not context_sources else "Merge + Context"
        return "Transform" if not context_sources else "Transform + Context"

    @staticmethod
    def _get_output_fields(
        action_config: Dict[str, Any], schema_dir: Optional[Path] = None
    ) -> List[str]:
        """Extract output field names from action config schema."""
        import yaml

        # Check inline schema first
        schema = action_config.get("schema", {})
        if schema:
            if isinstance(schema, dict):
                # Could be {"field": "type"} or {"properties": {...}}
                if "properties" in schema:
                    return list(schema["properties"].keys())
                # Simple format: {"field_name": "string", ...}
                return list(schema.keys())

        # Check schema_name reference and load from file
        schema_name = action_config.get("schema_name")
        if schema_name:
            # Try to load schema file
            if schema_dir is None:
                schema_dir = Path.cwd() / "schema"

            schema_file = schema_dir / f"{schema_name}.yml"
            if schema_file.exists():
                try:
                    with open(schema_file, "r") as f:
                        schema_data = yaml.safe_load(f)
                    if schema_data:
                        # Handle JSON Schema format with properties
                        if "properties" in schema_data:
                            return list(schema_data["properties"].keys())
                        # Handle simple format
                        if isinstance(schema_data, dict):
                            # Filter out JSON Schema keywords
                            keywords = {
                                "type",
                                "description",
                                "required",
                                "$schema",
                                "title",
                                "additionalProperties",
                            }
                            fields = [k for k in schema_data.keys() if k not in keywords]
                            if fields:
                                return fields
                except Exception as e:
                    logger.debug("Failed to read schema '%s': %s", schema_name, e, exc_info=True)
            return [f"[schema: {schema_name}]"]

        return []

    @staticmethod
    def _get_input_fields(action_config: Dict[str, Any]) -> List[str]:
        """Get input fields from context_scope observe/passthrough."""
        fields = []
        ctx = action_config.get("context_scope", {})
        for field_ref in ctx.get("observe", []):
            fields.append(f"{field_ref} (observe)")
        for field_ref in ctx.get("passthrough", []):
            fields.append(f"{field_ref} (passthrough)")
        return fields


@click.group(name="inspect")
def inspect():
    """Inspect workflow structure and data flow."""


# =============================================================================
# Dependencies Command
# =============================================================================


class DependenciesCommand(BaseInspectCommand):
    """Show dependency analysis in table format."""

    def __init__(
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        action_filter: Optional[str],
    ):
        super().__init__(agent, user_code, json_output)
        self.action_filter = action_filter

    def execute(self) -> None:
        if not self.json_output:
            self.console.print(f"[cyan]Dependency Analysis: {self.agent_name}[/cyan]\n")

        workflow = self._load_workflow()
        dependency_info = self._analyze_dependencies(workflow)

        if self.json_output:
            self._output_json(dependency_info)
        else:
            self._output_rich(dependency_info, workflow.execution_order)

    def _output_json(self, dependency_info: Dict[str, Any]) -> None:
        output = {"workflow": self.agent_name, "actions": dependency_info}
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, dependency_info: Dict[str, Any], execution_order: list) -> None:
        if self.action_filter:
            if self.action_filter not in dependency_info:
                self.console.print(f"[red]Action '{self.action_filter}' not found[/red]")
                self.console.print(f"[dim]Available: {', '.join(dependency_info.keys())}[/dim]")
                return
            dependency_info = {self.action_filter: dependency_info[self.action_filter]}

        # Deprecation warnings
        deprecated = [n for n, i in dependency_info.items() if i["has_primary_dependency"]]
        if deprecated:
            self.console.print("[yellow]⚠ Deprecated 'primary_dependency' in:[/yellow]")
            for name in deprecated:
                self.console.print(f"  • {name}")
            self.console.print("[dim]Use 'dependencies' instead[/dim]\n")

        # Table
        table = Table(title="Dependency Model", show_lines=True)
        table.add_column("Action", style="bold")
        table.add_column("Input Sources", style="green")
        table.add_column("Context Sources", style="yellow")
        table.add_column("Type", style="cyan")

        order = execution_order if execution_order else list(dependency_info.keys())
        for name in order:
            if name not in dependency_info:
                continue
            info = dependency_info[name]
            inputs = info["input_sources"]
            contexts = info["context_sources"]

            input_str = ", ".join(inputs) if inputs else "[dim]source data[/dim]"
            context_str = ", ".join(contexts) if contexts else "[dim]none[/dim]"
            action_type = self._get_action_type(inputs, contexts)

            table.add_row(name, input_str, context_str, action_type)

        self.console.print(table)


@inspect.command(name="dependencies")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--action", "action_filter", required=False, help="Filter to specific action")
@handles_user_errors("inspect dependencies")
@requires_project
def dependencies(
    agent: str, user_code: Optional[str], json_output: bool, action_filter: Optional[str]
) -> None:
    """
    Analyze workflow dependencies and auto-inferred context.

    Shows input sources (execution dependencies) and context sources
    (auto-inferred from context_scope) for each action.

    Examples:
        agac inspect dependencies -a my_workflow
        agac inspect dependencies -a my_workflow --action extract_facts
    """
    DependenciesCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_filter=action_filter
    ).execute()


# =============================================================================
# Graph Command
# =============================================================================


class GraphCommand(BaseInspectCommand):
    """Show workflow structure as a visual dependency graph."""

    def execute(self) -> None:
        workflow = self._load_workflow()
        dependency_info = self._analyze_dependencies(workflow)
        execution_order = workflow.execution_order or list(workflow.agent_configs.keys())

        if self.json_output:
            self._output_json(workflow, dependency_info, execution_order)
        else:
            self._output_rich(workflow, dependency_info, execution_order)

    def _output_json(
        self,
        workflow: AgentWorkflow,
        dependency_info: Dict[str, Any],
        execution_order: List[str],
    ) -> None:
        output = {
            "workflow": self.agent_name,
            "execution_order": execution_order,
            "actions": {
                name: {
                    "type": self._get_action_type(info["input_sources"], info["context_sources"]),
                    "input_sources": info["input_sources"],
                    "context_sources": info["context_sources"],
                    "output_fields": self._get_output_fields(workflow.agent_configs.get(name, {})),
                }
                for name, info in dependency_info.items()
            },
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(
        self,
        workflow: AgentWorkflow,
        dependency_info: Dict[str, Any],
        execution_order: List[str],
    ) -> None:
        # Header
        flow_str = " → ".join(execution_order) if execution_order else "none"
        self.console.print(f"[bold cyan]Workflow: {self.agent_name}[/bold cyan]")
        self.console.print(f"[dim]Flow: {flow_str}[/dim]\n")

        # Tree view
        tree = Tree("[bold]Actions[/bold]")

        for action_name in execution_order:
            if action_name not in dependency_info:
                continue

            info = dependency_info[action_name]
            action_config = workflow.agent_configs.get(action_name, {})
            action_type = self._get_action_type(info["input_sources"], info["context_sources"])

            # Action node
            node = tree.add(f"[bold]{action_name}[/bold] [dim]({action_type})[/dim]")

            # Kind (if not llm)
            kind = action_config.get("kind", "llm")
            if kind != "llm":
                node.add(f"[dim]kind: {kind}[/dim]")

            # Input sources
            if info["input_sources"]:
                for src in info["input_sources"]:
                    node.add(f"[green]← {src}[/green]")
            else:
                node.add("[green]← source data[/green]")

            # Context sources
            for src in info["context_sources"]:
                node.add(f"[yellow]◇ {src}[/yellow] [dim](context)[/dim]")

            # Output fields
            output_fields = self._get_output_fields(action_config)
            if output_fields:
                outputs_str = ", ".join(output_fields)
                node.add(f"[magenta]→ {outputs_str}[/magenta]")

        self.console.print(tree)
        self.console.print("\n[dim]← input  ◇ context  → output[/dim]")


@inspect.command(name="graph")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@handles_user_errors("inspect graph")
@requires_project
def graph(agent: str, user_code: Optional[str], json_output: bool) -> None:
    """
    Show workflow structure as a dependency graph.

    Displays how actions connect: which actions feed into others
    and which provide context data.

    Examples:
        agac inspect graph -a my_workflow
        agac inspect graph -a my_workflow --json
    """
    GraphCommand(agent=agent, user_code=user_code, json_output=json_output).execute()


# =============================================================================
# Action Command
# =============================================================================


class ActionCommand(BaseInspectCommand):
    """Show detailed information about a single action."""

    def __init__(
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.action_name = action_name

    def execute(self) -> None:
        workflow = self._load_workflow()

        if self.action_name not in workflow.agent_configs:
            self.console.print(f"[red]Action '{self.action_name}' not found[/red]")
            self.console.print(f"[dim]Available: {', '.join(workflow.agent_configs.keys())}[/dim]")
            return

        action_config = workflow.agent_configs[self.action_name]
        dependency_info = self._analyze_dependencies(workflow)
        info = dependency_info[self.action_name]

        if self.json_output:
            self._output_json(action_config, info)
        else:
            self._output_rich(action_config, info)

    def _output_json(self, action_config: Dict[str, Any], info: Dict[str, Any]) -> None:
        output = {
            "workflow": self.agent_name,
            "action": self.action_name,
            "type": self._get_action_type(info["input_sources"], info["context_sources"]),
            "kind": action_config.get("kind", "llm"),
            "model": action_config.get("model_name"),
            "input_sources": info["input_sources"],
            "context_sources": info["context_sources"],
            "context_scope": info["context_scope"],
            "output_fields": self._get_output_fields(action_config),
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(self, action_config: Dict[str, Any], info: Dict[str, Any]) -> None:
        action_type = self._get_action_type(info["input_sources"], info["context_sources"])

        # Header
        self.console.print(f"[bold cyan]Action: {self.action_name}[/bold cyan]")
        self.console.print(f"[dim]Type: {action_type}[/dim]\n")

        # Config
        kind = action_config.get("kind", "llm")
        model = action_config.get("model_name", "default")
        granularity = action_config.get("granularity", "record")

        config_table = Table(show_header=False, box=None, padding=(0, 2))
        config_table.add_column(style="bold")
        config_table.add_column()
        config_table.add_row("Kind:", kind)
        config_table.add_row("Model:", model)
        config_table.add_row("Granularity:", granularity)
        self.console.print(Panel(config_table, title="Configuration", border_style="dim"))

        # Dependencies
        tree = Tree("[bold]Dependencies[/bold]")

        if info["input_sources"]:
            branch = tree.add("[green]Input Sources[/green]")
            for src in info["input_sources"]:
                branch.add(f"• {src}")
        else:
            tree.add("[green]Input Sources[/green]: [dim]source data[/dim]")

        if info["context_sources"]:
            branch = tree.add("[yellow]Context Sources[/yellow]")
            for src in info["context_sources"]:
                branch.add(f"• {src}")
        else:
            tree.add("[yellow]Context Sources[/yellow]: [dim]none[/dim]")

        self.console.print(tree)

        # Context scope (input fields)
        ctx = info["context_scope"]
        if ctx["observe"] or ctx["passthrough"]:
            self.console.print()
            scope_tree = Tree("[bold]Input Fields (from context_scope)[/bold]")
            if ctx["observe"]:
                obs = scope_tree.add("[cyan]observe:[/cyan]")
                for f in ctx["observe"]:
                    obs.add(f"• {f}")
            if ctx["passthrough"]:
                pas = scope_tree.add("[cyan]passthrough:[/cyan]")
                for f in ctx["passthrough"]:
                    pas.add(f"• {f}")
            self.console.print(scope_tree)

        # Output fields (from schema)
        output_fields = self._get_output_fields(action_config)
        if output_fields:
            self.console.print()
            out_tree = Tree("[bold]Output Fields (from schema)[/bold]")
            for f in output_fields:
                out_tree.add(f"[magenta]• {f}[/magenta]")
            self.console.print(out_tree)

        # Deprecation
        if info["has_primary_dependency"]:
            self.console.print("\n[yellow]⚠ Uses deprecated 'primary_dependency'[/yellow]")


@inspect.command(name="action")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name")
@handles_user_errors("inspect action")
@requires_project
def action(agent: str, user_code: Optional[str], json_output: bool, action_name: str) -> None:
    """
    Show details for a specific action.

    Displays configuration, dependencies, and context scope.

    Examples:
        agac inspect action -a my_workflow extract_facts
        agac inspect action -a my_workflow generate_question --json
    """
    ActionCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute()


# =============================================================================
# Context Command
# =============================================================================


class ContextCommand(BaseInspectCommand):
    """Show context debug information for a specific action."""

    def __init__(
        self,
        agent: str,
        user_code: Optional[str],
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.target_action_name = action_name

    def execute(self) -> None:
        workflow = self._load_workflow()

        if self.target_action_name not in workflow.agent_configs:
            self.console.print(f"[red]Action '{self.target_action_name}' not found[/red]")
            self.console.print(f"[dim]Available: {', '.join(workflow.agent_configs.keys())}[/dim]")
            return

        action_config = workflow.agent_configs[self.target_action_name]
        dependency_info = self._analyze_dependencies(workflow)
        info = dependency_info[self.target_action_name]

        # Get schema directory for output field extraction
        schema_dir = self.paths.schema_dir if self.paths else None

        # Build context debug data
        context_data = self._build_context_data(workflow, action_config, info, schema_dir)

        if self.json_output:
            self._output_json(context_data)
        else:
            self._output_rich(context_data)

    def _build_context_data(
        self,
        workflow,
        action_config: Dict[str, Any],
        info: Dict[str, Any],
        schema_dir: Optional[Path],
    ) -> Dict[str, Any]:
        """Build comprehensive context debug data for the action."""
        # Get all namespaces that would be available
        namespaces = {}

        # Source namespace is always available
        namespaces["source"] = ["[from source data]"]

        # Add dependency namespaces
        for dep in info["input_sources"]:
            dep_config = workflow.agent_configs.get(dep, {})
            dep_fields = self._get_output_fields(dep_config, schema_dir)
            namespaces[dep] = dep_fields if dep_fields else ["[schema fields]"]

        # Add context source namespaces
        for dep in info["context_sources"]:
            dep_config = workflow.agent_configs.get(dep, {})
            dep_fields = self._get_output_fields(dep_config, schema_dir)
            namespaces[dep] = dep_fields if dep_fields else ["[schema fields]"]

        # Add special namespaces
        namespaces["version"] = ["i", "idx", "length", "first", "last"]
        namespaces["workflow"] = ["name", "run_id"]

        # Get context scope
        context_scope = action_config.get("context_scope", {})

        # Get output fields
        output_fields = self._get_output_fields(action_config, schema_dir)

        # Count total template variables
        total_vars = sum(len(fields) for fields in namespaces.values())

        return {
            "action_name": self.target_action_name,
            "workflow": self.agent_name,
            "namespaces": namespaces,
            "context_scope": {
                "observe": context_scope.get("observe", []),
                "passthrough": context_scope.get("passthrough", []),
                "drop": context_scope.get("drop", []),
            },
            "dependencies": {
                "input_sources": info["input_sources"],
                "context_sources": info["context_sources"],
            },
            "output_fields": output_fields,
            "total_template_variables": total_vars,
        }

    def _output_json(self, context_data: Dict[str, Any]) -> None:
        click.echo(json_lib.dumps(context_data, indent=2))

    def _output_rich(self, context_data: Dict[str, Any]) -> None:
        action_name = context_data["action_name"]

        self.console.print()
        self.console.print(
            f"[bold cyan]=== Context Debug for action '{action_name}' ===[/bold cyan]"
        )
        self.console.print()

        # Namespaces loaded
        namespaces = context_data.get("namespaces", {})
        if namespaces:
            tree = Tree("[bold]Namespaces loaded:[/bold]")
            for ns, fields in namespaces.items():
                field_str = ", ".join(fields[:5])
                if len(fields) > 5:
                    field_str += f"... (+{len(fields) - 5} more)"
                tree.add(f"[green]{ns}[/green]: {len(fields)} fields [{field_str}]")
            self.console.print(tree)
            self.console.print()

        # Context scope
        scope = context_data.get("context_scope", {})
        if scope.get("observe") or scope.get("passthrough") or scope.get("drop"):
            tree = Tree("[bold]Context scope applied:[/bold]")
            if scope.get("observe"):
                tree.add(f"[cyan]observe:[/cyan] {', '.join(scope['observe'])}")
            if scope.get("passthrough"):
                tree.add(f"[cyan]passthrough:[/cyan] {', '.join(scope['passthrough'])}")
            if scope.get("drop"):
                tree.add(f"[cyan]drop:[/cyan] {', '.join(scope['drop'])}")
            self.console.print(tree)
            self.console.print()

        # Template variables
        if namespaces:
            tree = Tree("[bold]Template variables available:[/bold]")
            for ns, fields in namespaces.items():
                vars_str = ", ".join(f"{{{{ {ns}.{f} }}}}" for f in fields[:3])
                if len(fields) > 3:
                    vars_str += f", ... (+{len(fields) - 3} more)"
                tree.add(f"[magenta]{vars_str}[/magenta]")
            self.console.print(tree)
            self.console.print()

        # Dependencies
        deps = context_data.get("dependencies", {})
        if deps.get("input_sources") or deps.get("context_sources"):
            tree = Tree("[bold]Dependencies:[/bold]")
            if deps.get("input_sources"):
                tree.add(f"[green]input_sources:[/green] {', '.join(deps['input_sources'])}")
            if deps.get("context_sources"):
                tree.add(f"[yellow]context_sources:[/yellow] {', '.join(deps['context_sources'])}")
            self.console.print(tree)
            self.console.print()

        # Output fields
        output_fields = context_data.get("output_fields", [])
        if output_fields:
            tree = Tree("[bold]Output fields (from schema):[/bold]")
            for f in output_fields:
                tree.add(f"[magenta]{f}[/magenta]")
            self.console.print(tree)
            self.console.print()


@inspect.command(name="context")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name")
@handles_user_errors("inspect context")
@requires_project
def context(agent: str, user_code: Optional[str], json_output: bool, action_name: str) -> None:
    """
    Show context debug information for a specific action.

    Displays available namespaces, context scope rules, and template variables
    that would be available during template rendering.

    Examples:
        agac inspect context -a my_workflow extract_facts
        agac inspect context -a my_workflow generate_question --json
    """
    ContextCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute()
