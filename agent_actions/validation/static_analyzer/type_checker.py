"""Static type checker for workflow field references."""

import difflib
import re

from agent_actions.utils.constants import (
    RESERVED_NAMES_NO_RECORD_HAS,
    SPECIAL_NAMESPACES,
    VERDICT_KEY,
)

from .data_flow_graph import DataFlowGraph, DataFlowNode, InputRequirement, OutputSchema
from .errors import (
    FieldLocation,
    StaticTypeError,
    StaticTypeWarning,
    StaticValidationResult,
    read_through_reserved_name,
)

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")

# Besides a guard, the places that read an upstream's stored namespace. A `drop` names a
# field on its way into the action's context and is checked as before.
_NAMESPACE_READS = frozenset({"prompt", "context_scope.observe", "context_scope.passthrough"})


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case (e.g. ``hitlStatus`` → ``hitl_status``)."""
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _admits_unlisted(output_schema: OutputSchema) -> bool:
    """Whether the schema, or the schema of each of its items, sets `additionalProperties`."""
    schema = output_schema.json_schema
    if not isinstance(schema, dict):
        return False
    items = schema.get("items")
    return any(
        isinstance(part, dict) and part.get("additionalProperties") not in (None, False)
        for part in (schema, items)
    )


class StaticTypeChecker:
    """Performs static type checking on workflow data flow graph."""

    def __init__(
        self,
        graph: DataFlowGraph,
    ) -> None:
        """Initialize the type checker."""
        self.graph = graph

    def check_all(self) -> StaticValidationResult:
        """Run all static type checks on the graph."""
        result = StaticValidationResult()

        try:
            order = self.graph.topological_sort()
        except ValueError as e:
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

        for action_name in order:
            node = self.graph.get_node(action_name)
            if node and not self.graph.is_special_namespace(action_name):
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
        """Check a single input requirement against the graph."""
        source_agent = requirement.source_agent
        field_path = requirement.field_path

        location = FieldLocation(
            agent_name=node.name,
            config_field=requirement.location,
            raw_reference=requirement.raw_reference,
        )

        if source_agent in RESERVED_NAMES_NO_RECORD_HAS:
            problem, fix = read_through_reserved_name(
                source_agent,
                requirement.raw_reference,
                field_path,
                self.graph.get_all_agent_names(),
            )
            result.add_error(
                StaticTypeError(
                    message=f"Action '{node.name}' {requirement.location} {problem}",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint=fix,
                )
            )
            return

        if source_agent in SPECIAL_NAMESPACES:
            return

        # A guard naming its own action, or one not upstream of it through its
        # dependencies, is refused by `find_reads_not_upstream` in words about the guard.
        is_guard = requirement.location == "guard"
        if is_guard and source_agent == node.name:
            return

        source_node = self.graph.get_node(source_agent)
        if not source_node:
            available_agents = sorted(self.graph.get_all_agent_names())
            closest = sorted(difflib.get_close_matches(source_agent, available_agents, n=3))
            hint = (
                f"Available actions: {', '.join(available_agents)}"
                if available_agents
                else "No actions found in workflow"
            )
            if closest:
                hint = f"Did you mean {' or '.join(repr(n) for n in closest)}? {hint}"
            result.add_error(
                StaticTypeError(
                    message=f"Referenced action '{source_agent}' does not exist in workflow",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint=hint,
                )
            )
            return

        if source_agent != node.name and not is_guard:
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
                            f"Add '{source_agent}' to dependencies for '{node.name}' "
                            "or ensure it is reachable via upstream dependencies"
                        ),
                    )
                )
                return

        output_schema = source_node.output_schema

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

        root_field = field_path.split(".")[0]

        # "*" is a wildcard directive (observe/passthrough all), not a field name
        if root_field == "*" or root_field.isdigit():
            return

        reads_namespace = is_guard or requirement.location in _NAMESPACE_READS
        if reads_namespace:
            # A read of the action's namespace finds it as stored: what it produced and the
            # verdict its expectations attach, never what it observed or passed through
            # (a passed-through field is stored under the namespace it came from).
            if root_field == VERDICT_KEY:
                return
            available = output_schema.schema_fields
        else:
            available = output_schema.available_fields

        # The record as stored also keeps a field an open schema (`additionalProperties`)
        # admits without listing it.
        if reads_namespace and root_field not in available and _admits_unlisted(output_schema):
            result.add_warning(
                StaticTypeWarning(
                    message=f"Cannot validate field '{field_path}' - "
                    f"action '{source_agent}' has a schema that allows fields it does not list",
                    location=location,
                    referenced_agent=source_agent,
                    referenced_field=field_path,
                    hint=f"List '{root_field}' in the schema of '{source_agent}' "
                    "for it to be checked",
                )
            )
            return

        if root_field not in available:
            # Try camelCase → snake_case normalization.  The HITL runtime
            # converts field names to snake_case, so user configs may
            # reference ``hitlStatus`` while the canonical schema uses
            # ``hitl_status``.
            snake_field = _camel_to_snake(root_field)
            if snake_field != root_field and snake_field in available:
                return  # Accepted — runtime will normalize

            if not reads_namespace and output_schema.drops_field(root_field):
                result.add_error(
                    StaticTypeError(
                        message=f"Field '{root_field}' has been dropped from "
                        f"action '{source_agent}' output",
                        location=location,
                        referenced_agent=source_agent,
                        referenced_field=field_path,
                        available_fields=available,
                        hint=f"Remove '{root_field}' from context_scope.drop in "
                        f"action '{source_agent}', or use a different field",
                    )
                )
            else:
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

        field_lower = field.lower()
        similar = []
        for avail in available:
            avail_lower = avail.lower()
            if field_lower in avail_lower or avail_lower in field_lower:
                similar.append(avail)
            elif field_lower[:3] == avail_lower[:3]:  # Same prefix
                similar.append(avail)

        if similar:
            return f"Did you mean: {', '.join(similar)}?"

        return f"Available fields: {', '.join(sorted(available))}"

    def check_unused_dependencies(self) -> list[StaticTypeWarning]:
        """Find declared dependencies that are never referenced."""
        warnings: list[StaticTypeWarning] = []

        for action_name, node in self.graph.nodes.items():
            if self.graph.is_special_namespace(action_name):
                continue

            referenced = set()
            for req in node.input_requirements:
                referenced.add(req.source_agent)

            # Don't flag special namespaces (source, action, etc.) as unused —
            # they are implicit and always available
            unused = node.dependencies - referenced
            unused -= SPECIAL_NAMESPACES

            for dep in unused:
                warnings.append(
                    StaticTypeWarning(
                        message=f"Dependency '{dep}' is declared but never referenced",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field="dependencies",
                            raw_reference=dep,
                        ),
                        referenced_agent=dep,
                        referenced_field="",
                        hint=f"Either use fields from '{dep}' or remove it from dependencies",
                    )
                )

        return warnings

    def check_missing_dependencies(self) -> list[StaticTypeWarning]:
        """Find actions referenced but not declared in dependencies."""
        warnings: list[StaticTypeWarning] = []

        for action_name, node in self.graph.nodes.items():
            if self.graph.is_special_namespace(action_name):
                continue

            referenced = set()
            for req in node.input_requirements:
                if req.source_agent not in SPECIAL_NAMESPACES:
                    referenced.add(req.source_agent)

            # An action that does not exist is refused by `_check_requirement`; it is no
            # dependency to add.
            implicit = {
                agent for agent in referenced - node.dependencies if self.graph.get_node(agent)
            }

            for agent in sorted(implicit):
                for req in node.input_requirements:
                    if req.source_agent == agent:
                        warnings.append(
                            StaticTypeWarning(
                                message=f"Implicit dependency on '{agent}' (not in dependencies)",
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=req.location,
                                    raw_reference=req.raw_reference,
                                ),
                                referenced_agent=agent,
                                referenced_field=req.field_path,
                                hint=f"Consider adding '{agent}' to dependencies for clarity",
                            )
                        )
                        break

        return warnings
