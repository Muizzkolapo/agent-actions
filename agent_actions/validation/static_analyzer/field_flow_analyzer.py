"""Field flow analyzer for workflow data lineage tracking."""

from dataclasses import dataclass, field
from typing import Any

from .data_flow_graph import DataFlowGraph, DataFlowNode
from .errors import StaticValidationResult


@dataclass
class FieldConsumer:
    """A consumer of a field."""

    agent: str
    location: str
    raw_reference: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent": self.agent,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class FieldLineage:
    """Tracks a field's production, transformation, and consumption through the workflow."""

    producer: str
    field_name: str
    field_type: str  # 'schema', 'observe', 'passthrough', 'source'
    consumers: list[FieldConsumer] = field(default_factory=list)
    is_dropped: bool = False

    def to_dict(self) -> dict[str, Any]:
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
    """Information about an action's output fields."""

    schema_fields: list[str] = field(default_factory=list)
    observe_fields: list[str] = field(default_factory=list)
    passthrough_fields: list[str] = field(default_factory=list)
    dropped_fields: list[str] = field(default_factory=list)
    available_fields: list[str] = field(default_factory=list)
    is_dynamic: bool = False
    is_schemaless: bool = False

    def to_dict(self) -> dict[str, Any]:
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
    """A field reference from an upstream agent."""

    source_agent: str
    field: str
    location: str
    raw_reference: str

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_agent": self.source_agent,
            "field": self.field,
            "location": self.location,
            "raw_reference": self.raw_reference,
        }


@dataclass
class InputSchemaInfo:
    """Information about an action's input schema (for tools)."""

    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    is_dynamic: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "is_dynamic": self.is_dynamic,
        }


@dataclass
class ActionFlowInfo:
    """Complete input/output field flow information for a single action."""

    name: str
    kind: str
    inputs: list[FieldReference] = field(default_factory=list)
    input_schema: InputSchemaInfo = field(default_factory=InputSchemaInfo)
    outputs: OutputFieldInfo = field(default_factory=OutputFieldInfo)
    dependencies: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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
    """Complete field flow for a workflow."""

    workflow_name: str
    actions: list[ActionFlowInfo] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)
    field_lineages: dict[str, FieldLineage] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "workflow_name": self.workflow_name,
            "actions": [a.to_dict() for a in self.actions],
            "execution_order": self.execution_order,
            "field_lineages": {k: v.to_dict() for k, v in self.field_lineages.items()},
        }


class FieldFlowAnalyzer:
    """Analyzes field lineage and flow through a workflow."""

    def __init__(
        self,
        graph: DataFlowGraph,
        validation_result: StaticValidationResult,
        workflow_name: str = "",
    ):
        """Initialize the field flow analyzer."""
        self.graph = graph
        self.validation_result = validation_result
        self.workflow_name = workflow_name

    def get_full_flow(self) -> WorkflowFlow:
        """Get complete field flow for the entire workflow."""
        try:
            execution_order = self.graph.topological_sort()
        except ValueError:
            # Circular dependency - use whatever order we have
            execution_order = list(self.graph.nodes.keys())

        actions = []
        for action_name in execution_order:
            node = self.graph.get_node(action_name)
            if node:
                action_info = self._build_action_flow_info(node)
                actions.append(action_info)

        field_lineages = self._build_all_field_lineages()

        return WorkflowFlow(
            workflow_name=self.workflow_name,
            actions=actions,
            execution_order=execution_order,
            field_lineages=field_lineages,
        )

    def get_field_lineage(self, agent_name: str, field_name: str) -> FieldLineage | None:
        """Trace a single field from production to all consumption points."""
        node = self.graph.get_node(agent_name)
        if not node:
            return None

        output_schema = node.output_schema

        field_type = self._get_field_type(output_schema, field_name)
        if field_type is None:
            return None

        is_dropped = field_name in output_schema.dropped_fields
        consumers = self._find_field_consumers(agent_name, field_name)

        return FieldLineage(
            producer=agent_name,
            field_name=field_name,
            field_type=field_type,
            consumers=consumers,
            is_dropped=is_dropped,
        )

    def get_action_flow_info(self, agent_name: str) -> ActionFlowInfo | None:
        """Get field flow info for a single action."""
        node = self.graph.get_node(agent_name)
        if not node:
            return None
        return self._build_action_flow_info(node)

    def to_dict(self) -> dict[str, Any]:
        """Convert full analysis to dictionary for JSON serialization."""
        flow = self.get_full_flow()
        return {
            "workflow": self.workflow_name,
            "is_valid": self.validation_result.is_valid,
            "flow": flow.to_dict(),
            "validation": self.validation_result.to_dict(),
        }

    def _build_action_flow_info(self, node: DataFlowNode) -> ActionFlowInfo:
        """Build ActionFlowInfo from a DataFlowNode."""
        inputs = [
            FieldReference(
                source_agent=req.source_agent,
                field=req.field_path,
                location=req.location,
                raw_reference=req.raw_reference,
            )
            for req in node.input_requirements
        ]

        input_schema = InputSchemaInfo()
        if node.input_schema:
            input_schema = InputSchemaInfo(
                required_fields=sorted(node.input_schema.required_fields),
                optional_fields=sorted(node.input_schema.optional_fields),
                is_dynamic=node.input_schema.is_dynamic,
            )

        outputs = OutputFieldInfo(
            schema_fields=sorted(node.output_schema.schema_fields),
            observe_fields=sorted(node.output_schema.observe_fields),
            passthrough_fields=sorted(node.output_schema.passthrough_fields),
            dropped_fields=sorted(node.output_schema.dropped_fields),
            available_fields=sorted(node.output_schema.available_fields),
            is_dynamic=node.output_schema.is_dynamic,
            is_schemaless=node.output_schema.is_schemaless,
        )

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

    def _build_all_field_lineages(self) -> dict[str, FieldLineage]:
        """Build lineage for all fields in the workflow."""
        lineages: dict[str, FieldLineage] = {}

        for node in self.graph.nodes.values():
            output_schema = node.output_schema

            for field_name in output_schema.schema_fields:
                key = f"{node.name}.{field_name}"
                lineage = self.get_field_lineage(node.name, field_name)
                if lineage:
                    lineages[key] = lineage

            for field_name in output_schema.observe_fields:
                key = f"{node.name}.{field_name}"
                if key not in lineages:
                    lineage = self.get_field_lineage(node.name, field_name)
                    if lineage:
                        lineages[key] = lineage

            for field_name in output_schema.passthrough_fields:
                key = f"{node.name}.{field_name}"
                if key not in lineages:
                    lineage = self.get_field_lineage(node.name, field_name)
                    if lineage:
                        lineages[key] = lineage

        return lineages

    def _get_field_type(self, output_schema, field_name: str) -> str | None:
        """Determine how a field is produced."""
        if field_name in output_schema.schema_fields:
            return "schema"
        if field_name in output_schema.observe_fields:
            return "observe"
        if field_name in output_schema.passthrough_fields:
            return "passthrough"
        if output_schema.is_dynamic or output_schema.is_schemaless:
            return "source"
        return None

    def _find_field_consumers(self, producer_name: str, field_name: str) -> list[FieldConsumer]:
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

    def filter_to_field(self, agent_field: str) -> FieldLineage | None:
        """Filter analysis to a specific field in "agent.field" format."""
        if "." not in agent_field:
            return None

        parts = agent_field.split(".", 1)
        agent_name = parts[0]
        field_name = parts[1]

        return self.get_field_lineage(agent_name, field_name)
