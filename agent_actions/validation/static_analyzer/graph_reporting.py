"""Read-only views of the analyzer's data flow graph: schemas, summaries, execution order."""

from typing import TYPE_CHECKING, Any

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import (
    DataFlowGraph,
    DataFlowNode,
    InputSchema,
    OutputSchema,
)


class GraphReportingMixin:
    graph: DataFlowGraph
    _built: bool

    if TYPE_CHECKING:

        def _build_graph(self) -> None: ...

    def get_graph(self) -> DataFlowGraph:
        """Return the data flow graph for inspection.

        Returns:
            The built DataFlowGraph
        """
        if not self._built:
            self._build_graph()
        return self.graph

    def get_agent_schema(self, agent_name: str) -> OutputSchema | None:
        """Get the output schema for a specific action.

        Args:
            agent_name: Name of the action

        Returns:
            OutputSchema or None if action not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.output_schema if node else None

    def get_agent_input_schema(self, agent_name: str) -> InputSchema | None:
        """Get the input schema for a specific action.

        Args:
            agent_name: Name of the action

        Returns:
            InputSchema or None if action not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.input_schema if node else None

    def get_action_schemas(self) -> dict[str, dict[str, Any]]:
        """Get input and output schemas for all actions.

        Returns a dictionary mapping action names to their schemas:
        {
            "action_name": {
                "kind": "llm" | "tool" | "hitl",
                "input": {
                    "required": ["field1", "field2"],
                    "optional": ["field3"],
                    "is_template_based": True | False,
                    "is_dynamic": True | False
                },
                "output": {
                    "fields": ["field1", "field2"],
                    "is_schemaless": True | False,
                    "is_dynamic": True | False
                }
            }
        }
        """
        if not self._built:
            self._build_graph()

        result: dict[str, dict[str, Any]] = {}

        for name, node in self.graph.nodes.items():
            # Skip special namespaces
            if self.graph.is_special_namespace(name):
                continue

            action_info: dict[str, Any] = {
                "kind": node.agent_kind.value,
                "input": {},
                "output": {},
            }

            # Input schema
            if node.input_schema:
                action_info["input"] = {
                    "required": sorted(node.input_schema.required_fields),
                    "optional": sorted(node.input_schema.optional_fields),
                    "is_template_based": node.input_schema.is_template_based,
                    "is_dynamic": node.input_schema.is_dynamic,
                }
            else:
                action_info["input"] = {
                    "required": [],
                    "optional": [],
                    "is_template_based": False,
                    "is_dynamic": True,
                }

            # Output schema
            action_info["output"] = {
                "fields": sorted(node.output_schema.available_fields),
                "is_schemaless": node.output_schema.is_schemaless,
                "is_dynamic": node.output_schema.is_dynamic,
            }

            result[name] = action_info

        return result

    def _format_input_schema(self, input_info: dict[str, Any]) -> list[str]:
        """Format input schema section as lines."""
        if input_info["is_template_based"]:
            return ["    (template-based - see field references)"]
        if input_info["is_dynamic"]:
            return ["    (dynamic - determined at runtime)"]

        lines = []
        if input_info["required"]:
            lines.append(f"    required: {', '.join(input_info['required'])}")
        if input_info["optional"]:
            lines.append(f"    optional: {', '.join(input_info['optional'])}")
        if not lines:
            lines.append("    (no fields)")
        return lines

    def _format_output_schema(self, output_info: dict[str, Any]) -> list[str]:
        """Format output schema section as lines."""
        if output_info["is_schemaless"]:
            return ["    (schemaless - freeform output)"]
        if output_info["is_dynamic"]:
            return ["    (dynamic - determined at runtime)"]
        if output_info["fields"]:
            return [f"    fields: {', '.join(output_info['fields'])}"]
        return ["    (no fields)"]

    def format_action_schemas(self) -> str:
        """Format action schemas as a readable string.

        Returns:
            Formatted string showing input/output schemas for each action
        """
        schemas = self.get_action_schemas()
        lines = []

        for name, info in sorted(schemas.items()):
            lines.append(f"\n{name} ({info['kind']}):")
            lines.append("  Input:")
            lines.extend(self._format_input_schema(info["input"]))
            lines.append("  Output:")
            lines.extend(self._format_output_schema(info["output"]))

        return "\n".join(lines)

    def _get_execution_order(self) -> list[str]:
        """Get execution order; raises ValueError if a cycle is detected."""
        return self.graph.topological_sort()

    def _build_agent_references(self, node: DataFlowNode) -> list[dict[str, str]]:
        """Build references list for an action node."""
        return [
            {"agent": req.source_agent, "field": req.field_path}
            for req in node.input_requirements
            if req.source_agent not in SPECIAL_NAMESPACES
        ]

    def _build_agent_info(self, node: DataFlowNode) -> dict[str, Any]:
        """Build action info dictionary for a node."""
        return {
            "name": node.name,
            "kind": node.agent_kind.value,
            "output_fields": sorted(node.output_schema.available_fields),
            "dependencies": sorted(node.dependencies),
            "references": self._build_agent_references(node),
        }

    def get_data_flow_summary(self) -> dict[str, Any]:
        """Get a summary of data flow in the workflow.

        Returns:
            Dict with nodes, edges, and execution order
        """
        if not self._built:
            self._build_graph()

        execution_order = self._get_execution_order()

        return {
            "agents": [
                self._build_agent_info(node)
                for name, node in self.graph.nodes.items()
                if not self.graph.is_special_namespace(name)
            ],
            "execution_order": [
                n for n in execution_order if not self.graph.is_special_namespace(n)
            ],
            "edges": [
                {"from": edge.source, "to": edge.target, "fields": sorted(edge.fields_used)}
                for edge in self.graph.edges
            ],
        }
