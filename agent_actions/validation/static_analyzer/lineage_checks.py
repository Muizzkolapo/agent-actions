"""Lineage checks: drop targets and observed fields reachable through the dependency chain."""

from typing import Any

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import DataFlowGraph
from .errors import FieldLocation, StaticTypeError, StaticTypeWarning


class LineageChecksMixin:
    workflow_config: dict[str, Any]
    graph: DataFlowGraph

    def _check_drop_directives(
        self,
    ) -> tuple[list[StaticTypeError], list[StaticTypeWarning]]:
        """Validate that drop directives reference reachable schema/observe fields.

        Returns (errors, warnings).  Unreachable namespaces produce warnings
        (drops are defensive no-ops).  Invalid field references produce errors.
        """
        errors: list[StaticTypeError] = []
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            context_scope = action.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue
            drop_refs = context_scope.get("drop", [])
            if not isinstance(drop_refs, list):
                continue

            # Compute reachable upstream once per action (lazy).
            reachable: set[str] | None = None
            warned_unreachable: set[str] = set()

            for drop_ref in drop_refs:
                if not isinstance(drop_ref, str) or "." not in drop_ref:
                    continue

                dep_name, field_name = drop_ref.split(".", 1)

                if dep_name in SPECIAL_NAMESPACES or dep_name == "loop":
                    continue

                dep_node = self.graph.get_node(dep_name)
                if not dep_node:
                    continue  # Unknown dep — caught by expansion pass

                # Reachability check: is this namespace in the dependency chain?
                if reachable is None:
                    reachable = self.graph.get_reachable_upstream_names(action_name)
                if dep_name not in reachable:
                    if dep_name not in warned_unreachable:
                        warned_unreachable.add(dep_name)
                        warnings.append(
                            StaticTypeWarning(
                                message=(
                                    f"Drop directive targets namespace "
                                    f"'{dep_name}' in action '{action_name}', "
                                    f"but '{dep_name}' is not in its dependency "
                                    f"chain. This drop has no effect."
                                ),
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field="context_scope.drop",
                                    raw_reference=drop_ref,
                                ),
                                referenced_agent=dep_name,
                                referenced_field=field_name,
                                hint=(
                                    f"'{dep_name}' is not a dependency of "
                                    f"'{action_name}' — its fields will never "
                                    f"appear in context. Remove this drop or "
                                    f"add '{dep_name}.*' to context_scope.observe."
                                ),
                            )
                        )
                    continue

                output = dep_node.output_schema
                if output.is_dynamic or output.is_schemaless:
                    continue  # Can't validate

                if field_name in output.schema_fields or field_name in output.observe_fields:
                    continue  # Valid drop target

                if field_name in output.passthrough_fields:
                    errors.append(
                        StaticTypeError(
                            message=(
                                f"Drop directive '{drop_ref}' targets passthrough field "
                                f"'{field_name}' on '{dep_name}'. Passthrough fields are not "
                                f"in the LLM context namespace, so this drop has no effect."
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field="context_scope.drop",
                                raw_reference=drop_ref,
                            ),
                            referenced_agent=dep_name,
                            referenced_field=field_name,
                            available_fields=output.schema_fields | output.observe_fields,
                            hint=(
                                f"Remove this drop directive. '{field_name}' is a passthrough "
                                f"field — it doesn't appear in the LLM context. "
                                f"Schema fields: {', '.join(sorted(output.schema_fields))}"
                            ),
                        )
                    )
                elif field_name not in output.available_fields:
                    errors.append(
                        StaticTypeError(
                            message=(
                                f"Drop directive '{drop_ref}' references non-existent field "
                                f"'{field_name}' in '{dep_name}'"
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field="context_scope.drop",
                                raw_reference=drop_ref,
                            ),
                            referenced_agent=dep_name,
                            referenced_field=field_name,
                            available_fields=output.schema_fields | output.observe_fields,
                            hint=(
                                f"Available schema fields in '{dep_name}': "
                                f"{', '.join(sorted(output.schema_fields))}"
                            ),
                        )
                    )

        return errors, warnings

    def _check_lineage_reachability(self) -> list[StaticTypeWarning]:
        """Check that observe references to non-direct-dependencies are reachable.

        When action C observes ``A.field`` but C only depends on B (not A directly),
        the data must flow A → B → C via passthrough on B.  This check verifies
        the passthrough chain exists.
        """
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            node_name = action.get("name", "unknown")
            node = self.graph.get_node(node_name)
            if not node:
                continue

            context_scope = action.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue

            observe_refs = context_scope.get("observe", [])
            if not isinstance(observe_refs, list):
                continue

            for ref in observe_refs:
                if not isinstance(ref, str) or "." not in ref:
                    continue

                source_name, field_name = ref.split(".", 1)

                if source_name in SPECIAL_NAMESPACES or source_name == "loop":
                    continue
                # Remaining wildcards are dynamic/schemaless (known schemas
                # were expanded by _expand_wildcards).  Can't trace individual
                # fields through the chain, so skip lineage check.
                if field_name == "*":
                    continue

                # If source is a direct dependency, no lineage concern
                if source_name in node.dependencies:
                    continue

                # Source is NOT a direct dependency — must travel through intermediates
                reachable = self.graph.get_reachable_upstream_names(node_name)
                if source_name not in reachable:
                    continue  # Not reachable at all — caught by type checker

                if not self._trace_field_through_chain(source_name, field_name, node_name):
                    warnings.append(
                        StaticTypeWarning(
                            message=(
                                f"Observe reference '{ref}' on '{node_name}' references "
                                f"non-direct dependency '{source_name}'. The field "
                                f"'{field_name}' may not survive through intermediate "
                                f"actions via passthrough."
                            ),
                            location=FieldLocation(
                                agent_name=node_name,
                                config_field="context_scope.observe",
                                raw_reference=ref,
                            ),
                            referenced_agent=source_name,
                            referenced_field=field_name,
                            hint=(
                                f"Ensure intermediate actions between '{source_name}' and "
                                f"'{node_name}' have passthrough: ['{source_name}.*'] or "
                                f"passthrough: ['{source_name}.{field_name}'] in their "
                                f"context_scope."
                            ),
                        )
                    )

        return warnings

    def _trace_field_through_chain(self, source: str, field: str, target: str) -> bool:
        """Check if a field from *source* can reach *target* through passthrough chains.

        BFS backwards from *target* through dependencies.  At each intermediate
        node, checks whether the field survives (exact passthrough, wildcard
        passthrough, or dynamic schema).
        """
        from collections import deque

        target_node = self.graph.get_node(target)
        if not target_node:
            return False

        visited: set[str] = set()
        queue = deque(target_node.dependencies)

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if current == source:
                return True  # Direct path found

            current_node = self.graph.get_node(current)
            if not current_node:
                continue

            output = current_node.output_schema
            survives = (
                source in output.passthrough_wildcard_sources
                or field in output.passthrough_fields
                or output.is_dynamic
            )

            if survives:
                for dep in current_node.dependencies:
                    if dep not in visited:
                        queue.append(dep)

        return False
