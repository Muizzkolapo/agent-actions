"""Unified Rich rendering for schema display."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from agent_actions.models.action_schema import ActionKind, ActionSchema, FieldSource


class SchemaRenderer:
    """Unified Rich rendering for schema display."""

    def __init__(self, console: Console):
        self.console = console

    def render_summary_table(
        self,
        schemas: dict[str, ActionSchema],
        execution_order: list[str],
        title: str | None = None,
    ) -> Table:
        """Render a summary table of all actions."""
        table = Table(title=title, show_lines=True)
        table.add_column("Action", style="cyan", no_wrap=True)
        table.add_column("Type", style="magenta", width=6)
        table.add_column("Input", style="green")
        table.add_column("Output", style="yellow")

        for action_name in execution_order:
            schema = schemas.get(action_name)
            if not schema:
                continue

            input_str = self._format_input_summary(schema)
            output_str = self._format_output_summary(schema)
            table.add_row(action_name, schema.kind.value, input_str, output_str)

        return table

    def render_flow_tree(
        self,
        schemas: dict[str, ActionSchema],
        execution_order: list[str],
        verbose: bool = False,
    ) -> Tree:
        """Render workflow flow as a tree."""
        tree = Tree("[bold]Flow Visualization[/bold]")

        for action_name in execution_order:
            schema = schemas.get(action_name)
            if not schema:
                continue

            self._add_action_to_tree(tree, schema, verbose)

        return tree

    def render_action_detail(self, schema: ActionSchema) -> Panel:
        """Render detailed view of a single action."""
        tree = Tree(f"[bold cyan]{schema.name}[/bold cyan] ({schema.kind.value})")

        if schema.dependencies:
            deps_branch = tree.add("[blue]depends_on:[/blue]")
            for dep in schema.dependencies:
                deps_branch.add(dep)

        if schema.upstream_refs:
            inputs_branch = tree.add("[green]uses (from templates):[/green]")
            by_source: dict[str, list] = {}
            for ref in schema.upstream_refs:
                if ref.source_agent not in by_source:
                    by_source[ref.source_agent] = []
                by_source[ref.source_agent].append(ref)

            for source, refs in sorted(by_source.items()):
                source_branch = inputs_branch.add(f"[bold]{source}[/bold]")
                for ref in refs:
                    source_branch.add(f"{ref.field_name} [dim]({ref.location})[/dim]")

        if schema.kind == ActionKind.TOOL and schema.input_fields:
            schema_branch = tree.add("[green]expects (input schema):[/green]")
            for field in schema.input_fields:
                if field.is_required:
                    schema_branch.add(f"[bold]{field.name}[/bold] [dim](required)[/dim]")
                else:
                    schema_branch.add(f"{field.name} [dim](optional)[/dim]")

        self._add_outputs_to_tree(tree, schema)

        if schema.downstream:
            downstream_branch = tree.add("[magenta]downstream (used by):[/magenta]")
            for d in schema.downstream:
                downstream_branch.add(d)

        return Panel(tree, title=f"Action: {schema.name}")

    def render_data_flow_panel(
        self,
        schemas: dict[str, ActionSchema],
        execution_order: list[str],
    ) -> Panel:
        """Render a data flow panel (verbose tree view)."""
        tree = self.render_flow_tree(schemas, execution_order, verbose=True)
        return Panel(tree, title="Workflow Data Flow")

    def _format_input_summary(self, schema: ActionSchema) -> str:
        """Format input schema for summary display."""
        if schema.is_template_based:
            return "[dim](template-based)[/dim]"
        if schema.is_dynamic:
            return "[dim](dynamic)[/dim]"

        parts = []
        if schema.required_inputs:
            parts.append(f"[bold]required:[/bold] {', '.join(schema.required_inputs)}")
        if schema.optional_inputs:
            parts.append(f"[dim]optional:[/dim] {', '.join(schema.optional_inputs)}")

        return "\n".join(parts) if parts else "[dim](none)[/dim]"

    def _format_output_summary(self, schema: ActionSchema) -> str:
        """Format output schema for summary display."""
        if schema.is_schemaless:
            return "[dim](schemaless)[/dim]"
        if schema.is_dynamic:
            return "[dim](dynamic)[/dim]"

        fields = schema.available_outputs
        return ", ".join(fields) if fields else "[dim](none)[/dim]"

    def _add_action_to_tree(
        self,
        tree: Tree,
        schema: ActionSchema,
        verbose: bool = False,
    ) -> None:
        """Add an action node to the flow tree."""
        action_branch = tree.add(f"[cyan]{schema.name}[/cyan] ({schema.kind.value})")

        if schema.upstream_refs:
            inputs_branch = action_branch.add("[green]uses:[/green]")
            for ref in schema.upstream_refs:
                inputs_branch.add(f"{ref.source_agent}.{ref.field_name}")
        elif schema.kind == ActionKind.TOOL and schema.input_fields:
            inputs_branch = action_branch.add("[green]expects:[/green]")
            for field in schema.input_fields:
                if field.is_required:
                    inputs_branch.add(f"[bold]{field.name}[/bold]")
                else:
                    inputs_branch.add(f"{field.name} [dim](optional)[/dim]")
        elif schema.kind == ActionKind.SOURCE:
            action_branch.add("[dim](workflow input)[/dim]")

        self._add_outputs_to_tree(action_branch, schema, show_dropped=verbose)

        if verbose and schema.downstream:
            downstream_branch = action_branch.add("[magenta]downstream:[/magenta]")
            for d in schema.downstream:
                downstream_branch.add(d)

    def _add_outputs_to_tree(
        self,
        parent: Tree,
        schema: ActionSchema,
        show_dropped: bool = True,
    ) -> None:
        """Add output fields to a tree node."""
        if schema.available_outputs:
            outputs_branch = parent.add("[yellow]produces:[/yellow]")

            for field in schema.output_fields:
                if field.is_dropped:
                    continue

                if field.source == FieldSource.SCHEMA:
                    outputs_branch.add(f"[bold]{field.name}[/bold]")
                elif field.source == FieldSource.OBSERVE:
                    outputs_branch.add(f"{field.name} [dim](observe)[/dim]")
                elif field.source == FieldSource.PASSTHROUGH:
                    outputs_branch.add(f"{field.name} [dim](passthrough)[/dim]")
                else:
                    outputs_branch.add(field.name)

            if show_dropped and schema.dropped_outputs:
                dropped_branch = outputs_branch.add("[red]dropped:[/red]")
                for name in schema.dropped_outputs:
                    dropped_branch.add(f"[dim]{name}[/dim]")

        elif schema.is_dynamic:
            parent.add("[dim](dynamic output)[/dim]")
        elif schema.is_schemaless:
            parent.add("[dim](schemaless)[/dim]")
