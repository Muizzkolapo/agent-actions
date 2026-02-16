"""Data flow graph for workflow static analysis.

Represents the workflow as a directed graph where nodes are actions
and edges represent data dependencies.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from agent_actions.utils.constants import SPECIAL_NAMESPACES


class AgentKind(Enum):
    """Type of action node."""

    LLM = "llm"
    TOOL = "tool"
    HITL = "hitl"
    SOURCE = "source"  # Special: workflow input data
    SEED = "seed"  # Special: static seed data


@dataclass
class OutputSchema:
    """Represents the output schema of an action.

    Tracks fields from the schema definition, observe directives,
    passthrough fields, and dropped fields.

    Attributes:
        schema_fields: Fields from output schema (LLM generates these)
        observe_fields: Fields passed through from input via observe
        passthrough_fields: Fields from context_scope.passthrough
        dropped_fields: Fields excluded from output via drops
        json_schema: Full JSON schema for deep validation (optional)
        is_dynamic: Whether schema is determined at runtime
        is_schemaless: Whether action has no schema (freeform output)
    """

    schema_fields: Set[str] = field(default_factory=set)
    observe_fields: Set[str] = field(default_factory=set)
    passthrough_fields: Set[str] = field(default_factory=set)
    dropped_fields: Set[str] = field(default_factory=set)
    json_schema: Optional[Dict[str, Any]] = None
    is_dynamic: bool = False
    is_schemaless: bool = False

    @property
    def available_fields(self) -> Set[str]:
        """Compute available fields.

        Formula: (schema_fields + observe_fields + passthrough_fields) - dropped_fields
        """
        all_fields = self.schema_fields | self.observe_fields | self.passthrough_fields
        return all_fields - self.dropped_fields

    def has_field(self, field_name: str) -> bool:
        """Check if field is available in output."""
        return field_name in self.available_fields

    def __repr__(self) -> str:
        return f"OutputSchema(fields={sorted(self.available_fields)}, dynamic={self.is_dynamic})"


@dataclass
class InputSchema:
    """Represents the input schema of an action.

    Tracks what fields an action expects as input, either from:
    - Tool/UDF: explicit json_schema from UDF_REGISTRY (legacy with input_type)
    - Tool/UDF: inferred from context_scope (new style without input_type)
    - LLM: inferred from template variables

    Attributes:
        required_fields: Fields that must be provided
        optional_fields: Fields that can optionally be provided
        json_schema: Full JSON schema for validation (tools only)
        is_dynamic: Whether input schema is determined at runtime
        is_template_based: Whether inputs are inferred from templates (LLMs)
        derived_from_context_scope: Whether schema was inferred from context_scope
            (new style UDFs without input_type)
    """

    required_fields: Set[str] = field(default_factory=set)
    optional_fields: Set[str] = field(default_factory=set)
    json_schema: Optional[Dict[str, Any]] = None
    is_dynamic: bool = False
    is_template_based: bool = False
    derived_from_context_scope: bool = False

    @property
    def all_fields(self) -> Set[str]:
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
    """A field reference requirement from an action.

    Represents a single field reference found in the action's configuration.

    Attributes:
        source_agent: Action being referenced (e.g., 'extractor')
        field_path: Field being referenced (e.g., 'summary' or 'data.count')
        raw_reference: Original reference string (e.g., '{{ action.extractor.summary }}')
        location: Where it appears (e.g., 'prompt', 'guard')
    """

    source_agent: str
    field_path: str
    raw_reference: str
    location: str  # 'prompt', 'guard', 'context_scope.observe', etc.

    def __repr__(self) -> str:
        return f"InputRequirement({self.source_agent}.{self.field_path} in {self.location})"


@dataclass
class DataFlowNode:
    """Node in the data flow graph representing an action.

    Attributes:
        name: Action name
        agent_kind: Type of action (LLM, TOOL, HITL, SOURCE, etc.)
        output_schema: What fields this action produces
        input_schema: What fields this action expects as input
        input_requirements: What fields this action consumes from upstream
        dependencies: Explicit dependencies from depends_on config
    """

    name: str
    agent_kind: AgentKind
    output_schema: OutputSchema
    input_schema: Optional[InputSchema] = None
    input_requirements: List[InputRequirement] = field(default_factory=list)
    dependencies: Set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        return f"DataFlowNode({self.name}, kind={self.agent_kind.value})"


@dataclass
class DataFlowEdge:
    """Edge representing data flow from one action to another.

    Attributes:
        source: Source action name (producer)
        target: Target action name (consumer)
        fields_used: Which fields are referenced
    """

    source: str
    target: str
    fields_used: Set[str] = field(default_factory=set)

    def __repr__(self) -> str:
        return f"DataFlowEdge({self.source} -> {self.target}, fields={self.fields_used})"


class DataFlowGraph:
    """Graph representation of workflow data flow.

    Builds a directed graph where:
    - Nodes are actions (including special source/seed nodes)
    - Edges represent data dependencies between actions
    - Edge labels indicate which fields are used

    Used for static analysis of field references before execution.

    Example:
        graph = DataFlowGraph()

        # Add actions
        graph.add_node(DataFlowNode(
            name='extractor',
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={'summary', 'facts'}),
            dependencies=set()
        ))

        graph.add_node(DataFlowNode(
            name='summarizer',
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={'final_summary'}),
            input_requirements=[
                InputRequirement('extractor', 'summary', '{{ action.extractor.summary }}', 'prompt')
            ],
            dependencies={'extractor'}
        ))

        # Get execution order
        order = graph.topological_sort()  # ['extractor', 'summarizer']
    """

    # Use centralized constant from utils.constants
    # Special namespaces that are always available without explicit dependencies

    def __init__(self) -> None:
        self.nodes: Dict[str, DataFlowNode] = {}
        self.edges: List[DataFlowEdge] = []

    def add_node(self, node: DataFlowNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.name] = node

    def add_edge(self, edge: DataFlowEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)

    def get_node(self, name: str) -> Optional[DataFlowNode]:
        """Get a node by name."""
        return self.nodes.get(name)

    def has_node(self, name: str) -> bool:
        """Check if a node exists."""
        return name in self.nodes

    def is_special_namespace(self, name: str) -> bool:
        """Check if name is a special namespace (source, loop, etc.)."""
        return name in SPECIAL_NAMESPACES

    def get_upstream_nodes(self, agent_name: str) -> List[DataFlowNode]:
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

    def get_downstream_nodes(self, agent_name: str) -> List[DataFlowNode]:
        """Get all nodes that depend on this action."""
        downstream = []
        for node in self.nodes.values():
            if agent_name in node.dependencies:
                downstream.append(node)
        return downstream

    def get_reachable_upstream_names(self, agent_name: str) -> Set[str]:
        """Get all upstream action names reachable via dependencies.

        Args:
            agent_name: Action name to compute reachability for

        Returns:
            Set of action names that are dependencies or ancestors
        """
        node = self.nodes.get(agent_name)
        if not node:
            return set()

        reachable: Set[str] = set()
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

    def topological_sort(self) -> List[str]:
        """Return nodes in topological order (Kahn's algorithm).

        Returns:
            List of action names in execution order

        Raises:
            ValueError: If circular dependency detected
        """
        # Calculate in-degree for each node
        in_degree: Dict[str, int] = {name: 0 for name in self.nodes}

        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep in self.nodes:
                    in_degree[node.name] += 1

        # Start with nodes that have no dependencies
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            name = queue.pop(0)
            result.append(name)

            # Reduce in-degree for dependent nodes
            for action_name, node in self.nodes.items():
                if name in node.dependencies:
                    in_degree[action_name] -= 1
                    if in_degree[action_name] == 0:
                        queue.append(action_name)

        if len(result) != len(self.nodes):
            # Cycle detected
            remaining = set(self.nodes.keys()) - set(result)
            raise ValueError(f"Circular dependency detected involving: {remaining}")

        return result

    def build_edges_from_requirements(self) -> None:
        """Build edges based on input requirements of each node."""
        self.edges = []

        for node in self.nodes.values():
            # Group requirements by source action
            fields_by_source: Dict[str, Set[str]] = {}

            for req in node.input_requirements:
                if not self.is_special_namespace(req.source_agent):
                    if req.source_agent not in fields_by_source:
                        fields_by_source[req.source_agent] = set()
                    fields_by_source[req.source_agent].add(req.field_path)

            # Create edges
            for source_agent, fields in fields_by_source.items():
                edge = DataFlowEdge(
                    source=source_agent,
                    target=node.name,
                    fields_used=fields,
                )
                self.edges.append(edge)

    def get_all_agent_names(self) -> Set[str]:
        """Get names of all non-special action nodes."""
        return {name for name in self.nodes if not self.is_special_namespace(name)}

    def __repr__(self) -> str:
        node_count = len(self.nodes)
        edge_count = len(self.edges)
        return f"DataFlowGraph(nodes={node_count}, edges={edge_count})"
