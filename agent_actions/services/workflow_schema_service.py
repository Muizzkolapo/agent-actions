"""
Workflow schema service for unified schema access.
"""

from typing import Any, Dict, List, Optional

from agent_actions.models.action_schema import (
    ActionSchema,
    FieldInfo,
    FieldSource,
    UpstreamReference,
)
from agent_actions.validation.static_analyzer import (
    DataFlowGraph,
    DataFlowNode,
    StaticValidationResult,
    WorkflowStaticAnalyzer,
)


class WorkflowSchemaService:
    """Single source of truth for workflow schema analysis.

    Wraps WorkflowStaticAnalyzer and converts its data structures
    to the unified ActionSchema model.

    Attributes:
        workflow_name: Name of the workflow being analyzed
        analyzer: Underlying WorkflowStaticAnalyzer instance
    """

    def __init__(
        self,
        workflow_config: Dict[str, Any],
        udf_registry: Optional[Dict[str, Any]] = None,
        schema_loader: Optional[Any] = None,
        project_root: Optional[Any] = None,
        schema_dir: Optional[Any] = None,
    ):
        """Initialize the schema service.

        Args:
            workflow_config: Parsed workflow configuration dictionary
            udf_registry: UDF_REGISTRY for tool schema lookup
            schema_loader: SchemaLoader for external schema loading
            project_root: Project root for scanning tool functions
            schema_dir: Path to schema directory for external schemas
        """
        self._config = workflow_config
        self.workflow_name = workflow_config.get("name", "unknown")
        self._analyzer = WorkflowStaticAnalyzer(
            workflow_config,
            udf_registry=udf_registry,
            schema_loader=schema_loader,
            project_root=project_root,
            schema_dir=schema_dir,
        )
        self._schemas: Dict[str, ActionSchema] = {}
        self._validation_result: Optional[StaticValidationResult] = None

    @property
    def graph(self) -> DataFlowGraph:
        """Get the data flow graph."""
        return self._analyzer.get_graph()

    def get_action_schema(self, action_name: str) -> Optional[ActionSchema]:
        """Get unified schema for a single action.

        Args:
            action_name: Name of the action

        Returns:
            ActionSchema if action exists, None otherwise
        """
        if action_name in self._schemas:
            return self._schemas[action_name]

        node = self.graph.get_node(action_name)
        if not node:
            return None

        schema = self._build_action_schema(node)
        self._schemas[action_name] = schema
        return schema

    def get_all_schemas(self) -> Dict[str, ActionSchema]:
        """Get schemas for all actions.

        Returns:
            Dictionary mapping action names to their schemas
        """
        for name in self.graph.nodes:
            if not self.graph.is_special_namespace(name):
                self.get_action_schema(name)
        return self._schemas

    def validate(self) -> StaticValidationResult:
        """Run static validation on the workflow.

        Returns:
            StaticValidationResult with errors and warnings
        """
        if self._validation_result is None:
            self._validation_result = self._analyzer.analyze()
        return self._validation_result

    def get_execution_order(self) -> List[str]:
        """Get topological execution order of actions.

        Returns:
            List of action names in execution order (excludes special namespaces)
        """
        try:
            order = self.graph.topological_sort()
        except ValueError:
            order = list(self.graph.nodes.keys())

        return [name for name in order if not self.graph.is_special_namespace(name)]

    def get_downstream_actions(self, action_name: str) -> List[str]:
        """Get actions that depend on the given action.

        Args:
            action_name: Name of the action

        Returns:
            List of action names that depend on this action
        """
        downstream_nodes = self.graph.get_downstream_nodes(action_name)
        return sorted(node.name for node in downstream_nodes)

    def to_dict(self) -> Dict[str, Any]:
        """Convert full analysis to dictionary for JSON serialization.

        Returns:
            Dictionary with workflow name, schemas, execution order, and validation
        """
        validation = self.validate()
        return {
            "workflow_name": self.workflow_name,
            "is_valid": validation.is_valid,
            "execution_order": self.get_execution_order(),
            "actions": {name: schema.to_dict() for name, schema in self.get_all_schemas().items()},
            "validation": validation.to_dict(),
        }

    def _build_action_schema(self, node: DataFlowNode) -> ActionSchema:
        """Build ActionSchema from a DataFlowNode.

        Args:
            node: DataFlowNode from the graph

        Returns:
            ActionSchema with unified field representation
        """
        # Build upstream references from input requirements
        upstream_refs = [
            UpstreamReference(
                source_agent=req.source_agent,
                field_name=req.field_path,
                location=req.location,
                raw_reference=req.raw_reference,
            )
            for req in node.input_requirements
        ]

        # Build input fields (for tools with TypedDict input)
        input_fields = []
        if node.input_schema:
            for field_name in node.input_schema.required_fields:
                input_fields.append(
                    FieldInfo(
                        name=field_name,
                        source=FieldSource.TOOL_OUTPUT,
                        is_required=True,
                    )
                )
            for field_name in node.input_schema.optional_fields:
                input_fields.append(
                    FieldInfo(
                        name=field_name,
                        source=FieldSource.TOOL_OUTPUT,
                        is_required=False,
                    )
                )

        # Build output fields with source tracking
        output_fields = []
        out = node.output_schema

        for field_name in out.schema_fields:
            output_fields.append(
                FieldInfo(
                    name=field_name,
                    source=FieldSource.SCHEMA,
                    is_dropped=field_name in out.dropped_fields,
                )
            )

        for field_name in out.observe_fields:
            output_fields.append(
                FieldInfo(
                    name=field_name,
                    source=FieldSource.OBSERVE,
                    is_dropped=field_name in out.dropped_fields,
                )
            )

        for field_name in out.passthrough_fields:
            output_fields.append(
                FieldInfo(
                    name=field_name,
                    source=FieldSource.PASSTHROUGH,
                    is_dropped=field_name in out.dropped_fields,
                )
            )

        # Find downstream actions
        downstream = self.get_downstream_actions(node.name)

        # Determine is_template_based from input_schema
        is_template_based = False
        if node.input_schema:
            is_template_based = node.input_schema.is_template_based

        return ActionSchema(
            name=node.name,
            kind=node.agent_kind.value,
            upstream_refs=upstream_refs,
            input_fields=sorted(input_fields, key=lambda f: (not f.is_required, f.name)),
            output_fields=sorted(output_fields, key=lambda f: f.name),
            dependencies=sorted(node.dependencies),
            downstream=downstream,
            is_dynamic=out.is_dynamic,
            is_schemaless=out.is_schemaless,
            is_template_based=is_template_based,
        )
