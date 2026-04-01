"""Data flow graph for workflow static analysis."""

import collections
from dataclasses import dataclass, field
from typing import Any

from agent_actions.config.schema import ActionKind
from agent_actions.utils.constants import SPECIAL_NAMESPACES


@dataclass
class OutputSchema:
    """Represents the output schema of an action."""

    schema_fields: set[str] = field(default_factory=set)
    observe_fields: set[str] = field(default_factory=set)
    passthrough_fields: set[str] = field(default_factory=set)
    passthrough_wildcard_sources: set[str] = field(default_factory=set)
    dropped_fields: set[str] = field(default_factory=set)
    json_schema: dict[str, Any] | None = None
    is_dynamic: bool = False
    is_schemaless: bool = False
    load_error: str | None = None

    @property
    def available_fields(self) -> set[str]:
        """Compute available fields after applying drops."""
        all_fields = self.schema_fields | self.observe_fields | self.passthrough_fields
        return all_fields - self.dropped_fields

    def has_field(self, field_name: str) -> bool:
        """Check if field is available in output."""
        return field_name in self.available_fields

    def __repr__(self) -> str:
        return f"OutputSchema(fields={sorted(self.available_fields)}, dynamic={self.is_dynamic})"


@dataclass
class InputSchema:
    """Represents the input schema of an action."""

    required_fields: set[str] = field(default_factory=set)
    optional_fields: set[str] = field(default_factory=set)
    json_schema: dict[str, Any] | None = None
    is_dynamic: bool = False
    is_template_based: bool = False
    derived_from_context_scope: bool = False

    @property
    def all_fields(self) -> set[str]:
        """Get all input fields (required + optional)."""
        return self.required_fields | self.optional_fields

    def requires_field(self, field_name: str) -> bool:
        """Check if a field is required."""
        return field_name in self.required_fields

    def accepts_field(self, field_name: str) -> bool:
        """Check if a field is accepted (required or optional)."""
        return field_name in self.all_fields

    def __repr__(self) -> str:
        return (
            f"InputSchema(required={sorted(self.required_fields)}, "
            f"optional={sorted(self.optional_fields)})"
        )


@dataclass
class InputRequirement:
    """A single field reference found in an action's configuration."""

    source_agent: str
    field_path: str
    raw_reference: str
    location: str  # 'prompt', 'guard', 'context_scope.observe', etc.

    def __repr__(self) -> str:
        return f"InputRequirement({self.source_agent}.{self.field_path} in {self.location})"


@dataclass
class DataFlowNode:
    """Node in the data flow graph representing an action."""

    name: str
    agent_kind: ActionKind
    output_schema: OutputSchema
    input_schema: InputSchema | None = None
    input_requirements: list[InputRequirement] = field(default_factory=list)
    dependencies: set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        return f"DataFlowNode({self.name}, kind={self.agent_kind.value})"


@dataclass
class DataFlowEdge:
    """Edge representing data flow from one action to another."""

    source: str
    target: str
    fields_used: set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        return f"DataFlowEdge({self.source} -> {self.target}, fields={self.fields_used})"


class DataFlowGraph:
    """Directed graph of workflow data flow between action nodes."""

    def __init__(self) -> None:
        self.nodes: dict[str, DataFlowNode] = {}
        self.edges: list[DataFlowEdge] = []

    def add_node(self, node: DataFlowNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.name] = node

    def add_edge(self, edge: DataFlowEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)

    def get_node(self, name: str) -> DataFlowNode | None:
        """Get a node by name."""
        return self.nodes.get(name)

    def has_node(self, name: str) -> bool:
        """Check if a node exists."""
        return name in self.nodes

    def is_special_namespace(self, name: str) -> bool:
        """Check if name is a special namespace (source, loop, etc.)."""
        return name in SPECIAL_NAMESPACES

    def get_upstream_nodes(self, agent_name: str) -> list[DataFlowNode]:
        """Get all nodes that this action depends on."""
        node = self.nodes.get(agent_name)
        if not node:
            return []

        upstream = []
        for dep_name in node.dependencies:
            dep_node = self.nodes.get(dep_name)
            if dep_node:
                upstream.append(dep_node)

        return upstream

    def get_downstream_nodes(self, agent_name: str) -> list[DataFlowNode]:
        """Get all nodes that depend on this action."""
        downstream = []
        for node in self.nodes.values():
            if agent_name in node.dependencies:
                downstream.append(node)
        return downstream

    def get_reachable_upstream_names(self, agent_name: str) -> set[str]:
        """Get all upstream action names reachable via transitive dependencies."""
        node = self.nodes.get(agent_name)
        if not node:
            return set()

        reachable: set[str] = set()
        stack = list(node.dependencies)
        while stack:
            dep_name = stack.pop()
            if dep_name in reachable:
                continue
            reachable.add(dep_name)
            dep_node = self.nodes.get(dep_name)
            if dep_node:
                stack.extend(dep_node.dependencies - reachable)

        return reachable

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order.

        Raises:
            ValueError: If circular dependency detected.
        """
        in_degree: dict[str, int] = {name: 0 for name in self.nodes}
        dependents: dict[str, list[str]] = {name: [] for name in self.nodes}

        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in self.nodes:
                    in_degree[node.name] += 1
                    dependents[dep].append(node.name)

        queue: collections.deque[str] = collections.deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        result = []

        while queue:
            name = queue.popleft()
            result.append(name)

            for dep_name in dependents[name]:
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    queue.append(dep_name)

        if len(result) != len(self.nodes):
            remaining = set(self.nodes.keys()) - set(result)
            raise ValueError(f"Circular dependency detected involving: {remaining}")

        return result

    def build_edges_from_requirements(self) -> None:
        """Build edges based on input requirements of each node."""
        self.edges = []

        for node in self.nodes.values():
            fields_by_source: dict[str, set[str]] = {}

            for req in node.input_requirements:
                if not self.is_special_namespace(req.source_agent):
                    if req.source_agent not in fields_by_source:
                        fields_by_source[req.source_agent] = set()
                    fields_by_source[req.source_agent].add(req.field_path)

            for source_agent, fields in fields_by_source.items():
                edge = DataFlowEdge(
                    source=source_agent,
                    target=node.name,
                    fields_used=fields,
                )
                self.edges.append(edge)

    def get_all_agent_names(self) -> set[str]:
        """Get names of all non-special action nodes."""
        return {name for name in self.nodes if not self.is_special_namespace(name)}

    def __repr__(self) -> str:
        node_count = len(self.nodes)
        edge_count = len(self.edges)
        return f"DataFlowGraph(nodes={node_count}, edges={edge_count})"
