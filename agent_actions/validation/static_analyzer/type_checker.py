"""
Static type checker for workflow field references.
"""

from typing import List

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import DataFlowGraph, DataFlowNode, InputRequirement
from .errors import (
    FieldLocation,
    StaticTypeError,
    StaticTypeWarning,
    StaticValidationResult,
)


class StaticTypeChecker:
    """Performs static type checking on workflow data flow graph.

    Validates:
    1. All referenced actions exist and are in dependencies
    2. All referenced fields exist in upstream action's output schema
    3. Referenced fields haven't been dropped

    Example:
        graph = DataFlowGraph()
        # ... populate graph ...

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        if not result.is_valid:
            print(result.format_report())
    """

    # Use centralized SPECIAL_NAMESPACES from utils.constants

    def __init__(self, graph: DataFlowGraph) -> None:
        """Initialize the type checker.

        Args:
            graph: Data flow graph to validate
        """
        self.graph = graph

    def check_all(self) -> StaticValidationResult:
        """Run all static type checks on the graph.

        Returns:
            StaticValidationResult with all errors and warnings
        """
        result = StaticValidationResult()

        # Process nodes in topological order
        try:
            order = self.graph.topological_sort()
        except ValueError as e:
            # Circular dependency - this should be caught by dependency validator
            result.add_error(
                StaticTypeError(
                    message=str(e),
                    location=FieldLocation(agent_name="workflow", config_field="dependencies"),
                    referenced_agent="",
                    referenced_field="",
                    hint="Break the circular dependency by restructuring the workflow.",
                )
            )
            return result

        for node_name in order:
            node = self.graph.get_node(node_name)
            if node and not self.graph.is_special_namespace(node_name):
                self._check_node(node, result)

        return result

    def _check_node(self, node: DataFlowNode, result: StaticValidationResult) -> None:
        """Check a single node's input requirements."""
        for requirement in node.input_requirements:
            self._check_requirement(node, requirement, result)

    def _check_requirement(
        self,
        node: DataFlowNode,
        requirement: InputRequirement,
        result: StaticValidationResult,
    ) -> None:
        """Check a single input requirement.

        Validates:
        1. Source action exists (or is special namespace)
        2. Source action is reachable via dependencies
        3. Field exists in source action's output
        """
        source_agent = requirement.source_agent
        field_path = requirement.field_path

        # Create location for error reporting
        location = FieldLocation(
            agent_name=node.name,
            config_field=requirement.location,
            raw_reference=requirement.raw_reference,
        )

        # Skip special namespaces
        if source_agent in SPECIAL_NAMESPACES:
            return

        # Check 1: Source action exists
        source_node = self.graph.get_node(source_agent)
        if not source_node:
            available_agents = sorted(self.graph.get_all_agent_names())
            result.add_error(
                StaticTypeError(
                    message=f"Referenced action '{source_agent}' does not exist in workflow",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint=f"Available actions: {', '.join(available_agents)}"
                    if available_agents
                    else "No actions found in workflow",
                )
            )
            return

        # Check 2: Source action is reachable via dependencies
        if source_agent != node.name:
            reachable = self.graph.get_reachable_upstream_names(node.name)
            if source_agent not in reachable:
                result.add_error(
                    StaticTypeError(
                        message=(
                            f"Referenced action '{source_agent}' is not reachable from "
                            f"action '{node.name}'"
                        ),
                        location=location,
                        referenced_agent=source_agent,
                        referenced_field=field_path,
                        hint=(
                            f"Add '{source_agent}' to depends_on for '{node.name}' "
                            "or ensure it is reachable via upstream dependencies"
                        ),
                    )
                )
                return

        # Check 3: Field exists in output schema
        output_schema = source_node.output_schema

        # Handle schemaless actions (freeform output)
        if output_schema.is_schemaless:
            result.add_warning(
                StaticTypeWarning(
                    message=f"Cannot validate field '{field_path}' - "
                    f"action '{source_agent}' has no schema",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint=f"Consider adding a schema to '{source_agent}' for better validation",
                )
            )
            return

        # Handle dynamic schemas
        if output_schema.is_dynamic:
            result.add_warning(
                StaticTypeWarning(
                    message=f"Cannot validate field '{field_path}' - "
                    f"action '{source_agent}' has dynamic schema",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint="Schema is loaded at runtime and cannot be statically analyzed",
                )
            )
            return

        # Extract root field (first part of path)
        root_field = field_path.split(".")[0]

        # Handle array index access (e.g., items.0)
        if root_field.isdigit():
            # This is an array index - skip deep validation
            return

        # Check if field exists
        available = output_schema.available_fields

        if root_field not in available:
            # Check if it was explicitly dropped
            if root_field in output_schema.dropped_fields:
                result.add_error(
                    StaticTypeError(
                        message=f"Field '{root_field}' has been dropped from "
                        f"action '{source_agent}' output",
                        location=location,
                        referenced_agent=source_agent,
                        referenced_field=field_path,
                        available_fields=available,
                        hint=f"Remove '{root_field}' from the 'drops' list in "
                        f"action '{source_agent}', or use a different field",
                    )
                )
            else:
                # Suggest similar field names
                hint = self._suggest_similar_field(root_field, available)
                result.add_error(
                    StaticTypeError(
                        message=f"Field '{root_field}' not found in "
                        f"action '{source_agent}' output schema",
                        location=location,
                        referenced_agent=source_agent,
                        referenced_field=field_path,
                        available_fields=available,
                        hint=hint,
                    )
                )

    def _suggest_similar_field(self, field: str, available: set) -> str:
        """Suggest similar field names for typo correction."""
        if not available:
            return "No fields available in the source action's schema"

        # Simple similarity check (could use Levenshtein distance for better results)
        field_lower = field.lower()
        similar = []
        for avail in available:
            avail_lower = avail.lower()
            # Check for common typos
            if field_lower in avail_lower or avail_lower in field_lower:
                similar.append(avail)
            elif field_lower[:3] == avail_lower[:3]:  # Same prefix
                similar.append(avail)

        if similar:
            return f"Did you mean: {', '.join(similar)}?"

        return f"Available fields: {', '.join(sorted(available))}"

    def check_unused_dependencies(self) -> List[StaticTypeWarning]:
        """Find declared dependencies that are never referenced.

        Returns:
            List of warnings for unused dependencies
        """
        warnings: List[StaticTypeWarning] = []

        for node_name, node in self.graph.nodes.items():
            if self.graph.is_special_namespace(node_name):
                continue

            # Get all referenced actions from requirements
            referenced = set()
            for req in node.input_requirements:
                if req.source_agent not in SPECIAL_NAMESPACES:
                    referenced.add(req.source_agent)

            # Find unused dependencies
            unused = node.dependencies - referenced

            for dep in unused:
                warnings.append(
                    StaticTypeWarning(
                        message=f"Dependency '{dep}' is declared but never referenced",
                        location=FieldLocation(
                            agent_name=node_name,
                            config_field="depends_on",
                            raw_reference=dep,
                        ),
                        referenced_agent=dep,
                        referenced_field="",
                        hint=f"Either use fields from '{dep}' or remove it from depends_on",
                    )
                )

        return warnings

    def check_missing_dependencies(self) -> List[StaticTypeWarning]:
        """Find actions that are referenced but not declared in dependencies.

        Note: This returns WARNINGS, not errors, because the runtime automatically
        infers dependencies from references. Explicit depends_on is optional but
        recommended for clarity.

        Returns:
            List of warnings for implicit (undeclared) dependencies
        """
        warnings: List[StaticTypeWarning] = []

        for node_name, node in self.graph.nodes.items():
            if self.graph.is_special_namespace(node_name):
                continue

            # Get all referenced actions
            referenced = set()
            for req in node.input_requirements:
                if req.source_agent not in SPECIAL_NAMESPACES:
                    referenced.add(req.source_agent)

            # Find referenced but undeclared (implicit dependencies)
            implicit = referenced - node.dependencies

            for agent in implicit:
                # Find the first requirement referencing this action
                for req in node.input_requirements:
                    if req.source_agent == agent:
                        warnings.append(
                            StaticTypeWarning(
                                message=f"Implicit dependency on '{agent}' (not in depends_on)",
                                location=FieldLocation(
                                    agent_name=node_name,
                                    config_field=req.location,
                                    raw_reference=req.raw_reference,
                                ),
                                referenced_agent=agent,
                                referenced_field=req.field_path,
                                hint=f"Consider adding '{agent}' to depends_on for clarity",
                            )
                        )
                        break

        return warnings
