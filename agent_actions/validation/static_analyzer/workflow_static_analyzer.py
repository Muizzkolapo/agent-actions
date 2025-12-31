"""Main workflow static analyzer that orchestrates all components.

Provides a unified interface for static type checking of workflow configurations,
similar to TypeScript's compile-time type checking.
"""

from typing import Any, Dict, Optional

from .data_flow_graph import (
    AgentKind,
    DataFlowGraph,
    DataFlowNode,
    InputSchema,
    OutputSchema,
)
from .errors import StaticValidationResult
from .reference_extractor import ReferenceExtractor
from .schema_extractor import SchemaExtractor
from .type_checker import StaticTypeChecker


class WorkflowStaticAnalyzer:
    """Static analyzer for workflow type checking.

    Performs compile-time validation of workflow data flow,
    similar to TypeScript's type checking. Validates that all
    field references are valid before any execution.

    Example:
        # From workflow config dict
        analyzer = WorkflowStaticAnalyzer(workflow_config)
        result = analyzer.analyze()

        if not result.is_valid:
            print(result.format_report())
            raise ValueError("Static type checking failed")

        # From workflow file
        analyzer = WorkflowStaticAnalyzer.from_workflow_file("workflow.yml")
        result = analyzer.analyze()

    What it checks:
        1. All referenced agents exist in the workflow
        2. Referenced agents are declared in depends_on
        3. Referenced fields exist in upstream agent's output schema
        4. Fields haven't been dropped from output
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        workflow_config: Dict[str, Any],
        udf_registry: Optional[Dict[str, Any]] = None,
        schema_loader: Optional[Any] = None,
        source_schema: Optional[Dict[str, Any]] = None,
        schema_dir: Optional[Any] = None,
        project_root: Optional[Any] = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            workflow_config: Parsed workflow configuration dictionary
            udf_registry: UDF_REGISTRY for tool schema lookup (legacy, optional)
            schema_loader: SchemaLoader for external schema loading
            source_schema: Schema for source/input data (optional)
            schema_dir: Path to schema directory (defaults to cwd/schema)
            project_root: Project root for scanning tool functions
        """
        self.workflow_config = workflow_config
        self.schema_extractor = SchemaExtractor(
            udf_registry, schema_dir=schema_dir, project_root=project_root
        )
        self.reference_extractor = ReferenceExtractor()
        self.schema_loader = schema_loader
        self.source_schema = source_schema

        self.graph = DataFlowGraph()
        self._built = False

    def analyze(self) -> StaticValidationResult:
        """Perform static analysis of the workflow.

        Returns:
            StaticValidationResult with errors and warnings
        """
        # Step 1: Build data flow graph
        self._build_graph()

        # Step 2: Run type checker
        checker = StaticTypeChecker(self.graph)
        result = checker.check_all()

        # Step 3: Check for unused dependencies (add as warnings)
        warnings = checker.check_unused_dependencies()
        for warning in warnings:
            result.add_warning(warning)

        return result

    def _build_graph(self) -> None:
        """Build the data flow graph from workflow config."""
        if self._built:
            return

        # Add special source node (always available)
        self._add_source_node()

        # Add agent nodes from actions
        actions = self.workflow_config.get("actions", [])
        for action_config in actions:
            self._add_agent_node(action_config)

        # Build edges from input requirements
        self.graph.build_edges_from_requirements()

        self._built = True

    def _add_source_node(self) -> None:
        """Add the special source node for workflow input."""
        if self.source_schema:
            # Extract fields from provided source schema
            # pylint: disable=protected-access
            fields = self.schema_extractor._extract_fields_from_json_schema(self.source_schema)
            schema = OutputSchema(schema_fields=fields)
        else:
            # Source is dynamic - can have any fields
            schema = OutputSchema(is_dynamic=True)

        node = DataFlowNode(
            name="source",
            agent_kind=AgentKind.SOURCE,
            output_schema=schema,
        )
        self.graph.add_node(node)

    def _add_agent_node(self, action_config: Dict[str, Any]) -> None:
        """Add an agent node to the graph."""
        name = action_config.get("name", "unknown")

        # Determine agent type
        kind = action_config.get("kind", "llm")
        model_vendor = action_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            agent_kind = AgentKind.TOOL
        else:
            agent_kind = AgentKind.LLM

        # Extract output schema
        output_schema = self.schema_extractor.extract_schema(action_config, self.schema_loader)

        # Extract input schema (pass reference_extractor for LLM template analysis)
        input_schema = self.schema_extractor.extract_input_schema(
            action_config, self.reference_extractor
        )

        # Extract input requirements (field references)
        input_requirements = self.reference_extractor.extract_from_agent(action_config)

        # Get dependencies - support both 'depends_on' and 'dependencies' field names
        deps_list = action_config.get("depends_on") or action_config.get("dependencies", [])

        # Handle both string and dict dependencies
        dependencies = set()
        if isinstance(deps_list, list):
            for dep in deps_list:
                if isinstance(dep, str):
                    dependencies.add(dep)
                elif isinstance(dep, dict):
                    # Workflow dependency - skip for now (cross-workflow validation)
                    workflow_dep = dep.get("workflow")
                    if workflow_dep:
                        continue

        node = DataFlowNode(
            name=name,
            agent_kind=agent_kind,
            output_schema=output_schema,
            input_schema=input_schema,
            input_requirements=input_requirements,
            dependencies=dependencies,
        )

        self.graph.add_node(node)

    def get_graph(self) -> DataFlowGraph:
        """Return the data flow graph for inspection.

        Returns:
            The built DataFlowGraph
        """
        if not self._built:
            self._build_graph()
        return self.graph

    def get_agent_schema(self, agent_name: str) -> Optional[OutputSchema]:
        """Get the output schema for a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            OutputSchema or None if agent not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.output_schema if node else None

    def get_agent_input_schema(self, agent_name: str) -> Optional[InputSchema]:
        """Get the input schema for a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            InputSchema or None if agent not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.input_schema if node else None

    def get_action_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Get input and output schemas for all actions.

        Returns a dictionary mapping action names to their schemas:
        {
            "action_name": {
                "kind": "llm" | "tool",
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

        result: Dict[str, Dict[str, Any]] = {}

        for name, node in self.graph.nodes.items():
            # Skip special namespaces
            if self.graph.is_special_namespace(name):
                continue

            action_info: Dict[str, Any] = {
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

            if info["input"]["is_template_based"]:
                lines.append("    (template-based - see field references)")
            elif info["input"]["is_dynamic"]:
                lines.append("    (dynamic - determined at runtime)")
            else:
                if info["input"]["required"]:
                    lines.append(f"    required: {', '.join(info['input']['required'])}")
                if info["input"]["optional"]:
                    lines.append(f"    optional: {', '.join(info['input']['optional'])}")
                if not info["input"]["required"] and not info["input"]["optional"]:
                    lines.append("    (no fields)")

            lines.append("  Output:")
            if info["output"]["is_schemaless"]:
                lines.append("    (schemaless - freeform output)")
            elif info["output"]["is_dynamic"]:
                lines.append("    (dynamic - determined at runtime)")
            elif info["output"]["fields"]:
                lines.append(f"    fields: {', '.join(info['output']['fields'])}")
            else:
                lines.append("    (no fields)")

        return "\n".join(lines)

    def get_data_flow_summary(self) -> Dict[str, Any]:
        """Get a summary of data flow in the workflow.

        Returns:
            Dict with nodes, edges, and execution order
        """
        if not self._built:
            self._build_graph()

        try:
            execution_order = self.graph.topological_sort()
        except ValueError:
            execution_order = list(self.graph.nodes.keys())

        return {
            "agents": [
                {
                    "name": node.name,
                    "kind": node.agent_kind.value,
                    "output_fields": sorted(node.output_schema.available_fields),
                    "dependencies": sorted(node.dependencies),
                    "references": [
                        {"agent": req.source_agent, "field": req.field_path}
                        for req in node.input_requirements
                        if req.source_agent not in self.graph.SPECIAL_NAMESPACES
                    ],
                }
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

    @classmethod
    def from_workflow_file(
        cls,
        workflow_path: str,
        udf_registry: Optional[Dict[str, Any]] = None,
        schema_loader: Optional[Any] = None,
    ) -> "WorkflowStaticAnalyzer":
        """Create analyzer from workflow file path.

        Args:
            workflow_path: Path to workflow YAML file
            udf_registry: UDF_REGISTRY for tool schema lookup
            schema_loader: SchemaLoader for external schemas

        Returns:
            Configured WorkflowStaticAnalyzer
        """
        import yaml  # pylint: disable=import-outside-toplevel

        with open(workflow_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        return cls(config, udf_registry=udf_registry, schema_loader=schema_loader)


def analyze_workflow(
    workflow_config: Dict[str, Any],
    udf_registry: Optional[Dict[str, Any]] = None,
    schema_loader: Optional[Any] = None,
    strict: bool = False,
) -> StaticValidationResult:
    """Convenience function to analyze a workflow configuration.

    Args:
        workflow_config: Workflow configuration dictionary
        udf_registry: Optional UDF registry for tool schemas
        schema_loader: Optional schema loader for external schemas
        strict: If True, treat warnings as errors

    Returns:
        StaticValidationResult with errors and warnings
    """
    analyzer = WorkflowStaticAnalyzer(
        workflow_config,
        udf_registry=udf_registry,
        schema_loader=schema_loader,
    )
    result = analyzer.analyze()

    if strict:
        result.set_strict_mode(True)

    return result
