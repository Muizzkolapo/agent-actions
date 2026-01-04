"""Field flow analyzer for workflow data lineage tracking.

Analyzes how fields flow through a workflow, tracking:
- Which agents produce which fields
- Which agents consume which fields
- Field transformations (observe, passthrough, drop)
- Complete lineage from source to consumption

Example:
    from agent_actions.validation.static_analyzer import (
        WorkflowStaticAnalyzer,
        FieldFlowAnalyzer,
    )

    analyzer = WorkflowStaticAnalyzer(workflow_config)
    graph = analyzer.get_graph()
    result = analyzer.analyze()

    flow_analyzer = FieldFlowAnalyzer(graph, result)
    flow = flow_analyzer.get_full_flow()

    # Trace a specific field
    lineage = flow_analyzer.get_field_lineage("extractor", "summary")
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .data_flow_graph import DataFlowGraph, DataFlowNode
from .errors import StaticValidationResult


@dataclass
class FieldConsumer:
    """A consumer of a field.

    Attributes:
        agent: Name of the consuming agent
        location: Where the field is used (prompt, guard, context_scope.observe, etc.)
        raw_reference: Original reference string (e.g., '{{ action.extractor.summary }}')
    """

    agent: str
    location: str
    raw_reference: str

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent": self.agent,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class FieldLineage:
    """Represents a field's journey through the workflow.

    Tracks where a field is produced, how it's transformed, and where it's consumed.

    Attributes:
        producer: Agent that produces the field
        field_name: Name of the field
        field_type: How the field is produced ('schema', 'observe', 'passthrough', 'source')
        consumers: List of agents that consume this field
        is_dropped: Whether the field is dropped from output
    """

    producer: str
    field_name: str
    field_type: str  # 'schema', 'observe', 'passthrough', 'source'
    consumers: List[FieldConsumer] = field(default_factory=list)
    is_dropped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "producer": self.producer,
            "field_name": self.field_name,
            "field_type": self.field_type,
            "consumers": [c.to_dict() for c in self.consumers],
            "is_dropped": self.is_dropped,
        }


@dataclass
class OutputFieldInfo:
    """Information about an action's output fields.

    Categorizes fields by how they are produced.

    Attributes:
        schema_fields: Fields from output schema (LLM generates these)
        observe_fields: Fields passed through from input via observe
        passthrough_fields: Fields from context_scope.passthrough
        dropped_fields: Fields excluded from output via drops
        available_fields: Final computed available fields
    """

    schema_fields: List[str] = field(default_factory=list)
    observe_fields: List[str] = field(default_factory=list)
    passthrough_fields: List[str] = field(default_factory=list)
    dropped_fields: List[str] = field(default_factory=list)
    available_fields: List[str] = field(default_factory=list)
    is_dynamic: bool = False
    is_schemaless: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_fields": self.schema_fields,
            "observe_fields": self.observe_fields,
            "passthrough_fields": self.passthrough_fields,
            "dropped_fields": self.dropped_fields,
            "available_fields": self.available_fields,
            "is_dynamic": self.is_dynamic,
            "is_schemaless": self.is_schemaless,
        }


@dataclass
class FieldReference:
    """A field reference from an upstream agent.

    Attributes:
        source_agent: Agent being referenced
        field: Field being referenced
        location: Where it appears in config
        raw_reference: Original reference string
    """

    source_agent: str
    field: str
    location: str
    raw_reference: str

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_agent": self.source_agent,
            "field": self.field,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class InputSchemaInfo:
    """Information about an action's input schema (for tools).

    Attributes:
        required_fields: Fields required by the tool
        optional_fields: Fields that are optional
        is_dynamic: Whether input is dynamic (no schema)
    """

    required_fields: List[str] = field(default_factory=list)
    optional_fields: List[str] = field(default_factory=list)
    is_dynamic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "is_dynamic": self.is_dynamic,
        }


@dataclass
class ActionFlowInfo:
    """Field flow information for a single action.

    Provides complete input/output field information for an action.

    Attributes:
        name: Action name
        kind: Type of action (llm, tool, source, seed)
        inputs: Fields consumed from upstream agents (template references)
        input_schema: Input schema for tools (from TypedDict)
        outputs: Fields produced by this action
        dependencies: Declared dependencies
        downstream: Actions that depend on this one
    """

    name: str
    kind: str
    inputs: List[FieldReference] = field(default_factory=list)
    input_schema: InputSchemaInfo = field(default_factory=InputSchemaInfo)
    outputs: OutputFieldInfo = field(default_factory=OutputFieldInfo)
    dependencies: List[str] = field(default_factory=list)
    downstream: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "kind": self.kind,
            "inputs": [i.to_dict() for i in self.inputs],
            "input_schema": self.input_schema.to_dict(),
            "outputs": self.outputs.to_dict(),
            "dependencies": self.dependencies,
            "downstream": self.downstream,
        }


@dataclass
class WorkflowFlow:
    """Complete field flow for a workflow.

    Aggregates all field flow information for the entire workflow.

    Attributes:
        workflow_name: Name of the workflow
        actions: Flow information for each action
        execution_order: Topological order of actions
        field_lineages: Lineage for each field (key: "agent.field")
    """

    workflow_name: str
    actions: List[ActionFlowInfo] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    field_lineages: Dict[str, FieldLineage] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "workflow_name": self.workflow_name,
            "actions": [a.to_dict() for a in self.actions],
            "execution_order": self.execution_order,
            "field_lineages": {k: v.to_dict() for k, v in self.field_lineages.items()},
        }


class FieldFlowAnalyzer:
    """Analyzes field lineage and flow through a workflow.

    Uses the DataFlowGraph to trace how fields move from producers
    to consumers, tracking transformations along the way.

    Example:
        graph = analyzer.get_graph()
        result = analyzer.analyze()

        flow_analyzer = FieldFlowAnalyzer(graph, result)
        flow = flow_analyzer.get_full_flow()

        # Get lineage for a specific field
        lineage = flow_analyzer.get_field_lineage("extractor", "summary")
        print(f"Field produced by: {lineage.producer}")
        print(f"Consumed by: {[c.agent for c in lineage.consumers]}")
    """

    def __init__(
        self,
        graph: DataFlowGraph,
        validation_result: StaticValidationResult,
        workflow_name: str = "",
    ):
        """Initialize the field flow analyzer.

        Args:
            graph: DataFlowGraph from WorkflowStaticAnalyzer
            validation_result: Validation result with errors/warnings
            workflow_name: Name of the workflow being analyzed
        """
        self.graph = graph
        self.validation_result = validation_result
        self.workflow_name = workflow_name

    def get_full_flow(self) -> WorkflowFlow:
        """Get complete field flow for the entire workflow.

        Returns:
            WorkflowFlow with all actions, execution order, and field lineages
        """
        try:
            execution_order = self.graph.topological_sort()
        except ValueError:
            # Circular dependency - use whatever order we have
            execution_order = list(self.graph.nodes.keys())

        # Build action flow info for each action
        actions = []
        for action_name in execution_order:
            node = self.graph.get_node(action_name)
            if node:
                action_info = self._build_action_flow_info(node)
                actions.append(action_info)

        # Build field lineages
        field_lineages = self._build_all_field_lineages()

        return WorkflowFlow(
            workflow_name=self.workflow_name,
            actions=actions,
            execution_order=execution_order,
            field_lineages=field_lineages,
        )

    def get_field_lineage(self, agent_name: str, field_name: str) -> Optional[FieldLineage]:
        """Trace a single field from production to all consumption points.

        Args:
            agent_name: Name of the producing agent
            field_name: Name of the field to trace

        Returns:
            FieldLineage if field exists, None otherwise
        """
        node = self.graph.get_node(agent_name)
        if not node:
            return None

        output_schema = node.output_schema

        # Determine field type
        field_type = self._get_field_type(output_schema, field_name)
        if field_type is None:
            return None

        # Check if field is dropped
        is_dropped = field_name in output_schema.dropped_fields

        # Find all consumers
        consumers = self._find_field_consumers(agent_name, field_name)

        return FieldLineage(
            producer=agent_name,
            field_name=field_name,
            field_type=field_type,
            consumers=consumers,
            is_dropped=is_dropped,
        )

    def get_action_flow_info(self, agent_name: str) -> Optional[ActionFlowInfo]:
        """Get field flow info for a single action.

        Args:
            agent_name: Name of the action

        Returns:
            ActionFlowInfo if action exists, None otherwise
        """
        node = self.graph.get_node(agent_name)
        if not node:
            return None
        return self._build_action_flow_info(node)

    def to_dict(self) -> Dict[str, Any]:
        """Convert full analysis to dictionary for JSON serialization.

        Returns:
            Dictionary containing flow and validation data
        """
        flow = self.get_full_flow()
        return {
            "workflow": self.workflow_name,
            "is_valid": self.validation_result.is_valid,
            "flow": flow.to_dict(),
            "validation": self.validation_result.to_dict(),
        }

    def _build_action_flow_info(self, node: DataFlowNode) -> ActionFlowInfo:
        """Build ActionFlowInfo from a DataFlowNode."""
        # Build inputs from input requirements (template references)
        inputs = [
            FieldReference(
                source_agent=req.source_agent,
                field=req.field_path,
                location=req.location,
                raw_reference=req.raw_reference,
            )
            for req in node.input_requirements
        ]

        # Build input schema info (for tools with TypedDict input)
        input_schema = InputSchemaInfo()
        if node.input_schema:
            input_schema = InputSchemaInfo(
                required_fields=sorted(node.input_schema.required_fields),
                optional_fields=sorted(node.input_schema.optional_fields),
                is_dynamic=node.input_schema.is_dynamic,
            )

        # Build outputs
        outputs = OutputFieldInfo(
            schema_fields=sorted(node.output_schema.schema_fields),
            observe_fields=sorted(node.output_schema.observe_fields),
            passthrough_fields=sorted(node.output_schema.passthrough_fields),
            dropped_fields=sorted(node.output_schema.dropped_fields),
            available_fields=sorted(node.output_schema.available_fields),
            is_dynamic=node.output_schema.is_dynamic,
            is_schemaless=node.output_schema.is_schemaless,
        )

        # Find downstream agents
        downstream = [n.name for n in self.graph.get_downstream_nodes(node.name)]

        return ActionFlowInfo(
            name=node.name,
            kind=node.agent_kind.value,
            inputs=inputs,
            input_schema=input_schema,
            outputs=outputs,
            dependencies=sorted(node.dependencies),
            downstream=sorted(downstream),
        )

    def _build_all_field_lineages(self) -> Dict[str, FieldLineage]:
        """Build lineage for all fields in the workflow."""
        lineages: Dict[str, FieldLineage] = {}

        for node in self.graph.nodes.values():
            # Process all available fields
            output_schema = node.output_schema

            # Track schema fields
            for field_name in output_schema.schema_fields:
                key = f"{node.name}.{field_name}"
                lineage = self.get_field_lineage(node.name, field_name)
                if lineage:
                    lineages[key] = lineage

            # Track observe fields
            for field_name in output_schema.observe_fields:
                key = f"{node.name}.{field_name}"
                if key not in lineages:
                    lineage = self.get_field_lineage(node.name, field_name)
                    if lineage:
                        lineages[key] = lineage

            # Track passthrough fields
            for field_name in output_schema.passthrough_fields:
                key = f"{node.name}.{field_name}"
                if key not in lineages:
                    lineage = self.get_field_lineage(node.name, field_name)
                    if lineage:
                        lineages[key] = lineage

        return lineages

    def _get_field_type(self, output_schema, field_name: str) -> Optional[str]:
        """Determine how a field is produced.

        Returns 'schema', 'observe', 'passthrough', or None if not found.
        """
        if field_name in output_schema.schema_fields:
            return "schema"
        if field_name in output_schema.observe_fields:
            return "observe"
        if field_name in output_schema.passthrough_fields:
            return "passthrough"
        # For source/seed nodes with dynamic schemas
        if output_schema.is_dynamic or output_schema.is_schemaless:
            return "source"
        return None

    def _find_field_consumers(self, producer_name: str, field_name: str) -> List[FieldConsumer]:
        """Find all agents that consume a specific field."""
        consumers = []

        for node in self.graph.nodes.values():
            for req in node.input_requirements:
                if req.source_agent == producer_name and req.field_path == field_name:
                    consumers.append(
                        FieldConsumer(
                            agent=node.name,
                            location=req.location,
                            raw_reference=req.raw_reference,
                        )
                    )

        return consumers

    def filter_to_field(self, agent_field: str) -> Optional[FieldLineage]:
        """Filter analysis to a specific field.

        Args:
            agent_field: Field reference in "agent.field" format

        Returns:
            FieldLineage if field exists, None otherwise
        """
        if "." not in agent_field:
            return None

        parts = agent_field.split(".", 1)
        agent_name = parts[0]
        field_name = parts[1]

        return self.get_field_lineage(agent_name, field_name)
