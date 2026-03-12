"""Workflow schema service for unified schema access."""

from __future__ import annotations

from typing import Any, Optional

from agent_actions.models.action_schema import (
    ActionKind,
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
    """Single source of truth for workflow schema analysis."""

    def __init__(
        self,
        workflow_config: dict[str, Any],
        udf_registry: Optional[dict[str, Any]] = None,
        schema_loader: Optional[Any] = None,
        project_root: Optional[Any] = None,
        schema_dir: Optional[Any] = None,
    ):
        self._config = workflow_config
        self.workflow_name = workflow_config.get("name", "unknown")
        self._analyzer = WorkflowStaticAnalyzer(
            workflow_config,
            udf_registry=udf_registry,
            schema_loader=schema_loader,
            project_root=project_root,
            schema_dir=schema_dir,
        )
        self._schemas: dict[str, ActionSchema] = {}
        self._validation_result: Optional[StaticValidationResult] = None

    @property
    def graph(self) -> DataFlowGraph:
        """Return the data flow graph."""
        return self._analyzer.get_graph()

    def get_action_schema(self, action_name: str) -> Optional[ActionSchema]:
        """Return the ActionSchema for action_name, or None if it does not exist."""
        if action_name in self._schemas:
            return self._schemas[action_name]

        node = self.graph.get_node(action_name)
        if not node:
            return None

        schema = self._build_action_schema(node)
        self._schemas[action_name] = schema
        return schema

    def get_all_schemas(self) -> dict[str, ActionSchema]:
        """Return schemas for all actions."""
        for name in self.graph.nodes:
            if not self.graph.is_special_namespace(name):
                self.get_action_schema(name)
        return self._schemas

    def validate(self) -> StaticValidationResult:
        """Run static validation on the workflow."""
        if self._validation_result is None:
            self._validation_result = self._analyzer.analyze()
        return self._validation_result

    def get_execution_order(self) -> list[str]:
        """Return topological execution order of actions, excluding special namespaces."""
        try:
            order = self.graph.topological_sort()
        except ValueError:
            order = list(self.graph.nodes.keys())

        return [name for name in order if not self.graph.is_special_namespace(name)]

    def get_downstream_actions(self, action_name: str) -> list[str]:
        """Return sorted list of action names that depend on action_name."""
        downstream_nodes = self.graph.get_downstream_nodes(action_name)
        return sorted(node.name for node in downstream_nodes)

    def to_dict(self) -> dict[str, Any]:
        """Convert full analysis to dictionary for JSON serialization."""
        validation = self.validate()
        return {
            "workflow_name": self.workflow_name,
            "is_valid": validation.is_valid,
            "execution_order": self.get_execution_order(),
            "actions": {name: schema.to_dict() for name, schema in self.get_all_schemas().items()},
            "validation": validation.to_dict(),
        }

    def _build_action_schema(self, node: DataFlowNode) -> ActionSchema:
        """Build ActionSchema from a DataFlowNode."""
        upstream_refs = [
            UpstreamReference(
                source_agent=req.source_agent,
                field_name=req.field_path,
                location=req.location,
                raw_reference=req.raw_reference,
            )
            for req in node.input_requirements
        ]

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

        downstream = self.get_downstream_actions(node.name)

        is_template_based = False
        if node.input_schema:
            is_template_based = node.input_schema.is_template_based

        return ActionSchema(
            name=node.name,
            kind=ActionKind(node.agent_kind.value),
            upstream_refs=upstream_refs,
            input_fields=sorted(input_fields, key=lambda f: (not f.is_required, f.name)),
            output_fields=sorted(output_fields, key=lambda f: f.name),
            dependencies=sorted(node.dependencies),
            downstream=downstream,
            is_dynamic=out.is_dynamic,
            is_schemaless=out.is_schemaless,
            is_template_based=is_template_based,
        )
