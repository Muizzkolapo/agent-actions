"""Guard checks: literal type mismatches and null namespaces left by skip/filter guards."""

from typing import Any

from agent_actions.guards.consolidated_guard import GuardBehavior
from agent_actions.record.elsewhere import gathers, sends_elsewhere
from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .data_flow_graph import DataFlowGraph
from .errors import FieldLocation, StaticTypeWarning


def guard_clause_and_behavior(guard: Any) -> tuple[str, str] | None:
    """A guard's clause and its `on_false` behavior, or None when it has no clause.

    An expanded config holds them as `clause` and `behavior`, a raw one as `condition` and
    `on_false`. A bare SQL clause, and a dict that names no behavior, filters; a raw UDF
    condition that names none skips.
    """
    if isinstance(guard, str):
        return (guard, GuardBehavior.FILTER.value) if guard.strip() else None
    if not isinstance(guard, dict):
        return None
    clause = guard.get("clause") or guard.get("condition")
    if not isinstance(clause, str) or not clause.strip():
        return None
    behavior = guard.get("behavior") or guard.get("on_false")
    if not behavior:
        is_udf = clause.strip().startswith("udf:")
        behavior = GuardBehavior.SKIP if is_udf else GuardBehavior.FILTER
    return clause, str(behavior)


class GuardChecksMixin:
    workflow_config: dict[str, Any]
    graph: DataFlowGraph

    _GUARD_TYPE_CHECKED_OPERATORS = frozenset({"EQ", "NE", "LT", "LE", "GT", "GE"})

    _JSON_TYPE_FAMILIES = {
        "string": "string",
        "boolean": "boolean",
        "integer": "number",
        "number": "number",
        "array": "array",
        "object": "object",
    }

    def _check_guard_literal_type_mismatch(self) -> list[StaticTypeWarning]:
        """Warn when a guard comparison literal can never match the referenced
        field's declared schema type.

        ``producer.approved == true`` with ``approved`` declared ``string``
        evaluates false for every record regardless of data — with
        ``on_false: filter`` the whole dataset silently disappears. The
        runtime warns per record; this surfaces the same mismatch before any
        record is processed.
        """
        from agent_actions.input.preprocessing.parsing.ast_nodes import (
            ComparisonNode,
            FieldNode,
            LiteralNode,
            LogicalNode,
            families_never_comparable,
            format_node,
            value_type_family,
        )
        from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

        def iter_field_literal_comparisons(node):
            if isinstance(node, LogicalNode):
                yield from iter_field_literal_comparisons(node.left)
                if node.right is not None:
                    yield from iter_field_literal_comparisons(node.right)
            elif isinstance(node, ComparisonNode):
                if isinstance(node.left, FieldNode) and isinstance(node.right, LiteralNode):
                    yield node, node.left, node.right
                elif isinstance(node.left, LiteralNode) and isinstance(node.right, FieldNode):
                    yield node, node.right, node.left

        warnings: list[StaticTypeWarning] = []
        parser: WhereClauseParser | None = None

        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict):
                continue
            consumer_name = action.get("name", "unknown")
            read = guard_clause_and_behavior(action.get("guard"))
            if read is None:
                continue
            condition = read[0]
            if condition.strip().startswith("udf:"):
                continue

            if parser is None:
                parser = WhereClauseParser()
            parse_result = parser.parse(condition)
            if not parse_result.success or parse_result.ast is None:
                continue  # unparseable conditions are surfaced at evaluation time

            for comparison, field_node, literal_node in iter_field_literal_comparisons(
                parse_result.ast.root
            ):
                if comparison.operator.name not in self._GUARD_TYPE_CHECKED_OPERATORS:
                    continue
                if literal_node.value is None:
                    continue
                path = field_node.field_path
                if "." not in path:
                    continue
                producer_name, field_name = path.split(".", 1)
                if "." in field_name:
                    continue  # schema types are tracked per top-level field
                producer_node = self.graph.get_node(producer_name)
                if not producer_node:
                    continue
                producer_schema = producer_node.output_schema.json_schema
                if not producer_schema:
                    continue
                declared = self._extract_field_types_from_schema(producer_schema).get(field_name)
                if not isinstance(declared, str):
                    continue  # union types like ["string", "null"] stay unchecked
                declared_family = self._JSON_TYPE_FAMILIES.get(declared)
                literal_family = value_type_family(literal_node.value)
                if not families_never_comparable(declared_family, literal_family):
                    continue

                message = (
                    f"Guard on action '{consumer_name}': type mismatch in "
                    f"'{format_node(comparison)}' — '{path}' is declared "
                    f"'{declared}' in the schema of '{producer_name}' but the "
                    f"literal is {literal_family} ({literal_node.value!r}); the "
                    f"comparison outcome is decided by the types, not the data."
                )
                if declared_family == "string" and literal_family in ("boolean", "number"):
                    literal_value = literal_node.value
                    quoted = (
                        str(literal_value).lower()
                        if isinstance(literal_value, bool)
                        else str(literal_value)
                    )
                    hint = (
                        f"Quote the literal (e.g. {path} "
                        f'{comparison.operator.value} "{quoted}"), or change the '
                        f"schema type."
                    )
                elif declared_family == "boolean" and literal_family == "string":
                    hint = "Compare against true/false without quotes, or change the schema type."
                else:
                    hint = "Align the literal with the field's declared schema type."
                warnings.append(
                    StaticTypeWarning(
                        message=message,
                        location=FieldLocation(
                            agent_name=consumer_name,
                            config_field="guard",
                            raw_reference=path,
                        ),
                        referenced_agent=producer_name,
                        referenced_field=field_name,
                        hint=hint,
                    )
                )

        return warnings

    def _check_guard_skipped_observe_refs(self) -> list[StaticTypeWarning]:
        """Warn when observe refs target specific fields from skip-guarded actions.

        When an action has ``guard.on_false`` set to ``"skip"``, the entire
        action namespace is ``None`` at runtime (``{action_name: None}``).
        Observing a specific field like ``action.field`` will crash because
        ``None["field"]`` doesn't exist.  Wildcards (``action.*``) resolve to
        empty when skipped and are safe.

        Only ``on_false: "skip"`` is checked — ``"filter"`` removes individual
        records but the namespace still exists for remaining records. A field the
        action observes as optional is not warned about: it resolves to its default.
        """
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        skip_guarded: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name", "")
            read = guard_clause_and_behavior(action.get("guard"))
            if read is None:
                continue
            if read[1] == GuardBehavior.SKIP:
                skip_guarded.add(name)

        if not skip_guarded:
            return warnings

        for action in actions:
            if not isinstance(action, dict):
                continue
            consumer_name = action.get("name", "unknown")
            context_scope = action.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue
            observe_refs = context_scope.get("observe", [])
            if not isinstance(observe_refs, list):
                continue
            optional = context_scope.get("optional") or {}

            for ref in observe_refs:
                if not isinstance(ref, str) or "." not in ref or ref in optional:
                    continue
                source_name, field_name = ref.split(".", 1)
                if field_name == "*":
                    continue  # wildcards handle null gracefully
                if source_name not in skip_guarded:
                    continue

                warnings.append(
                    StaticTypeWarning(
                        message=(
                            f"'{source_name}.{field_name}' may be null at runtime. "
                            f"Action '{source_name}' has guard with on_false: \"skip\" "
                            f"— when the guard evaluates to false, the action's "
                            f"namespace is null."
                        ),
                        location=FieldLocation(
                            agent_name=consumer_name,
                            config_field="context_scope.observe",
                            raw_reference=ref,
                        ),
                        referenced_agent=source_name,
                        referenced_field=field_name,
                        hint=(
                            f"Mark the field optional ('{source_name}.{field_name}?'), "
                            f"use '{source_name}.*' instead of "
                            f"'{source_name}.{field_name}', or handle null in the "
                            f"downstream prompt or tool."
                        ),
                    )
                )

        return warnings

    def _check_filter_fanin_observe_hazard(self) -> list[StaticTypeWarning]:  # noqa: C901
        """Warn when observe refs target a filter-guarded action at a fan-in point.

        When action A has ``guard.on_false`` set to ``"filter"`` and a downstream
        action C depends on both A and B (fan-in), records filtered by A can still
        arrive at C via B.  The filtered action's namespace is null on those
        records, so ``observe: ["A.field"]`` crashes at runtime.

        Unlike ``_check_guard_skipped_observe_refs`` (which handles skip on any
        dep topology), this check specifically targets the fan-in case where
        filter creates a null namespace via an alternate dependency path.

        Emits one warning per (filtered_action, consumer_action) pair.
        """
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        # Step 1: Identify filter-guarded actions. A record one that sends elsewhere
        # filtered stays out of a fan-in below it, except at an action that gathers.
        filter_guarded: set[str] = set()
        elsewhere: set[str] = set()
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name", "")
            read = guard_clause_and_behavior(action.get("guard"))
            if read is None:
                continue
            if read[1] == GuardBehavior.FILTER:
                filter_guarded.add(name)
                if sends_elsewhere(action):
                    elsewhere.add(name)

        if not filter_guarded:
            return warnings

        from agent_actions.prompt.context.scope_inference import expand_version_base_names
        from agent_actions.validation.dep_observe_validator import upstream_through_dependencies

        action_configs = {
            action.get("name", "unknown"): action for action in actions if isinstance(action, dict)
        }
        upstream = upstream_through_dependencies(action_configs)

        # Step 2: Build dependency sets from raw config for each action. A declared
        # dependency delivers records (an input); a name only in context_scope is read
        # for context and delivers none, unless the action declares no dependencies.
        action_deps: dict[str, set[str]] = {}
        action_inputs: dict[str, set[str]] = {}
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name", "unknown")
            deps_list = action.get("dependencies", [])
            deps: set[str] = set()
            if isinstance(deps_list, list):
                for dep in deps_list:
                    if isinstance(dep, str):
                        deps.add(dep)
            declared = expand_version_base_names(sorted(deps), list(action_configs))
            # Also infer from context_scope references.
            context_scope = action.get("context_scope", {})
            if isinstance(context_scope, dict):
                for directive in ("observe", "passthrough"):
                    refs = context_scope.get(directive, [])
                    if isinstance(refs, list):
                        for ref in refs:
                            if isinstance(ref, str) and "." in ref:
                                ns = ref.split(".", 1)[0]
                                if ns not in SPECIAL_NAMESPACES:
                                    deps.add(ns)
            action_deps[name] = deps
            action_inputs[name] = set(declared) if declared else deps

        # Step 3: For each consumer with fan-in deps, check observe refs.
        warned_pairs: set[tuple[str, str]] = set()
        for action in actions:
            if not isinstance(action, dict):
                continue
            consumer_name = action.get("name", "unknown")
            deps = action_deps.get(consumer_name, set())

            # Fan-in requires at least 2 dependencies.
            if len(deps) < 2:
                continue

            context_scope = action.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue
            observe_refs = context_scope.get("observe", [])
            if not isinstance(observe_refs, list):
                continue
            optional = context_scope.get("optional") or {}

            # Find observe refs targeting filter-guarded actions (specific fields only).
            hazard_sources: dict[str, list[str]] = {}  # filtered_action -> [field_refs]
            for ref in observe_refs:
                if not isinstance(ref, str) or "." not in ref or ref in optional:
                    continue
                source_name, field_name = ref.split(".", 1)
                if field_name == "*":
                    continue  # wildcards are null-safe
                if source_name not in filter_guarded:
                    continue
                if source_name not in deps:
                    continue
                if source_name in elsewhere and not gathers(action):
                    continue
                hazard_sources.setdefault(source_name, []).append(ref)

            if not hazard_sources:
                continue

            # Identify alternate dependency paths: inputs that are NOT the filter-guarded
            # action and do not run below it, so a record it filtered can still arrive.
            for filtered_action, field_refs in hazard_sources.items():
                alt_deps = {
                    dep
                    for dep in action_inputs.get(consumer_name, set())
                    if dep != filtered_action and filtered_action not in upstream.get(dep, set())
                }
                if not alt_deps:
                    continue  # Every input passed the filter, or none bypasses it

                pair = (filtered_action, consumer_name)
                if pair in warned_pairs:
                    continue
                warned_pairs.add(pair)

                alt_dep_names = ", ".join(sorted(alt_deps))
                example_ref = field_refs[0]

                warnings.append(
                    StaticTypeWarning(
                        message=(
                            f"Action '{consumer_name}' observes '{example_ref}' but "
                            f"'{filtered_action}' has guard with on_false: \"filter\". "
                            f"Records may arrive at '{consumer_name}' via alternate "
                            f"dependency '{alt_dep_names}' with '{filtered_action}' "
                            f"namespace as null."
                        ),
                        location=FieldLocation(
                            agent_name=consumer_name,
                            config_field="context_scope.observe",
                            raw_reference=example_ref,
                        ),
                        referenced_agent=filtered_action,
                        referenced_field=field_refs[0].split(".", 1)[1],
                        hint=(
                            f"Consider: (1) Add a matching guard to '{consumer_name}', "
                            f"(2) Change '{filtered_action}' guard to on_false=\"skip\", "
                            f"(3) Use '{filtered_action}.*' (null-safe) instead of "
                            f"specific fields, or (4) Mark the field optional "
                            f"('{example_ref}?')."
                        ),
                    )
                )

        return warnings

    @staticmethod
    def _extract_field_types_from_schema(schema: dict[str, Any] | list) -> dict[str, str]:
        """Extract {field_name: type_string} from a JSON schema or list-style schema."""
        result: dict[str, str] = {}

        # A schema loaded by name is the schema file itself: `{name, fields: [...]}`.
        if isinstance(schema, dict) and isinstance(schema.get("fields"), list):
            schema = schema["fields"]

        if isinstance(schema, list):
            # List-style schema: [{"id": "field", "type": "object"}, ...]
            for item in schema:
                if isinstance(item, dict):
                    field_id = item.get("id") or item.get("name", "")
                    field_type = item.get("type", "")
                    if field_id and field_type:
                        result[field_id] = field_type
        elif isinstance(schema, dict):
            # Standard JSON Schema with "properties"
            props = schema.get("properties", {})
            if isinstance(props, dict):
                for field_id, field_def in props.items():
                    if isinstance(field_def, dict):
                        result[field_id] = field_def.get("type", "")
            # Also handle "items" for array schemas
            items = schema.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        field_id = item.get("id") or item.get("name", "")
                        field_type = item.get("type", "")
                        if field_id and field_type:
                            result[field_id] = field_type

        return result
