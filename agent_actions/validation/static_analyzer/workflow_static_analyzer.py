"""Main workflow static analyzer that orchestrates all components.

Provides a unified interface for static type checking of workflow configurations,
similar to TypeScript's compile-time type checking.
"""

import logging
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import SEED_CONFIG_KEYS
from agent_actions.utils.constants import (
    DEFAULT_ACTION_KIND,
    RESERVED_AGENT_NAMES,
    SPECIAL_NAMESPACES,
)

from .data_flow_graph import (
    ActionKind,
    DataFlowGraph,
    DataFlowNode,
    InputSchema,
    OutputSchema,
)
from .errors import FieldLocation, StaticTypeError, StaticTypeWarning, StaticValidationResult
from .reference_extractor import ReferenceExtractor
from .schema_extractor import SchemaExtractor

logger = logging.getLogger(__name__)
from .schema_structure_validator import SchemaStructureValidator
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
        1. All referenced actions exist in the workflow
        2. Referenced actions are declared in depends_on
        3. Referenced fields exist in upstream action's output schema
        4. Fields haven't been dropped from output
    """

    def __init__(
        self,
        workflow_config: dict[str, Any],
        udf_registry: dict[str, Any] | None = None,
        schema_loader: Any | None = None,
        source_schema: dict[str, Any] | None = None,
        project_root: Any | None = None,
        workflow_name: str | None = None,
        tool_schemas: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            workflow_config: Parsed workflow configuration dictionary
            udf_registry: UDF_REGISTRY for tool schema lookup (legacy, optional)
            schema_loader: SchemaLoader for external schema loading
            source_schema: Schema for source/input data (optional)
            project_root: Project root for scanning tool functions
            workflow_name: Workflow name for multi-level schema resolution
            tool_schemas: Pre-scanned tool function schemas (avoids redundant scans)
        """
        self.workflow_config = workflow_config
        self.schema_extractor = SchemaExtractor(
            udf_registry,
            project_root=project_root,
            tool_schemas=tool_schemas,
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

        # Step 2: Expand wildcard field references (namespace.* → concrete fields)
        expansion_errors = self._expand_wildcards()

        # Step 3: Run type checker
        checker = StaticTypeChecker(self.graph)
        result = checker.check_all()

        for error in expansion_errors:
            result.add_error(error)

        # Step 3b: Reserved action name validation
        for error in self._check_reserved_action_names():
            result.add_error(error)

        # Step 2c: Validate context_scope field references
        for error in self._check_context_scope_fields():
            result.add_error(error)

        # Step 2d: Catch seed_data/seed_path misuse in context_scope references
        for error in self._check_seed_reference_misuse():
            result.add_error(error)

        # Step 2e: Validate schema structures (pre-flight check)
        for error in self._check_schema_structures():
            result.add_error(error)

        # Step 2f: Validate drop directives target schema/observe fields
        drop_errors, drop_warnings = self._check_drop_directives()
        for error in drop_errors:
            result.add_error(error)
        for warning in drop_warnings:
            result.add_warning(warning)

        # Step 2g: Detect guard-nullable fields flowing into tool schemas
        for warning in self._check_guard_nullable_fields():
            result.add_warning(warning)

        # Step 3: Check for unused dependencies (add as warnings)
        warnings = checker.check_unused_dependencies()
        for warning in warnings:
            result.add_warning(warning)

        # Step 3b: Check lineage reachability for observe/passthrough references
        for warning in self._check_lineage_reachability():
            result.add_warning(warning)

        return result

    def _build_graph(self) -> None:
        """Build the data flow graph from workflow config."""
        if self._built:
            return

        # Add special source node (always available)
        self._add_source_node()

        # Add action nodes from actions
        actions = self.workflow_config.get("actions", [])
        for action_config in actions:
            self._add_agent_node(action_config)

        # Build edges from input requirements
        self.graph.build_edges_from_requirements()

        self._built = True

    # ── Wildcard expansion ────────────────────────────────────────────

    def _expand_wildcards(self) -> list[StaticTypeError]:
        """Expand ``namespace.*`` references into concrete field references.

        Treats ``namespace.*`` as syntactic sugar for listing every field in
        the namespace's output schema.  For actions with known schemas the
        wildcard is replaced in-place so downstream checks operate on concrete
        field refs.  Dynamic / schemaless schemas cannot be expanded and the
        ``*`` is left as-is (downstream checks already skip these).

        Unknown namespaces produce errors — the same treatment explicit field
        references receive.
        """
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            original_scope = action.get("context_scope")
            if not original_scope or not isinstance(original_scope, dict):
                continue

            # Shallow-copy so we don't mutate the caller's config.
            context_scope = {**original_scope}
            action["context_scope"] = context_scope

            for directive in ("observe", "passthrough", "drop"):
                refs = context_scope.get(directive)
                if not isinstance(refs, list):
                    continue

                expanded: list[str] = []
                for ref in refs:
                    if not isinstance(ref, str) or "." not in ref:
                        expanded.append(ref)
                        continue

                    ns_name, field_name = ref.split(".", 1)

                    if field_name != "*":
                        expanded.append(ref)
                        continue

                    # ── Wildcard reference: namespace.* ──

                    # Special namespaces and loop are runtime-provided; skip.
                    if ns_name in SPECIAL_NAMESPACES or ns_name == "loop":
                        expanded.append(ref)
                        continue

                    # Namespace must be a known action in the workflow.
                    dep_node = self.graph.get_node(ns_name)
                    if not dep_node:
                        errors.append(
                            StaticTypeError(
                                message=(
                                    f"Wildcard reference '{ref}' in "
                                    f"context_scope.{directive} of action "
                                    f"'{action_name}' targets unknown action "
                                    f"'{ns_name}'"
                                ),
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=ref,
                                ),
                                referenced_agent=ns_name,
                                referenced_field="*",
                                hint=(
                                    f"No action named '{ns_name}' exists in "
                                    f"this workflow. Check for typos."
                                ),
                            )
                        )
                        continue

                    output = dep_node.output_schema

                    # Dynamic — fields resolved at runtime, can't expand.
                    if output.is_dynamic:
                        expanded.append(ref)
                        continue

                    # Schemaless — no schema defined, zero fields to expand.
                    # Drop the ref: "give me everything" from nothing = nothing.
                    if output.is_schemaless:
                        continue

                    # Expand into concrete field references.
                    # Empty schemas also resolve to nothing (wildcard on zero
                    # fields = zero refs).
                    fields = output.schema_fields | output.observe_fields
                    expanded.extend(f"{ns_name}.{f}" for f in sorted(fields))

                context_scope[directive] = expanded

        return errors

    def _check_reserved_action_names(self) -> list[StaticTypeError]:
        """Return errors for actions using reserved names."""
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            if not isinstance(name, str):
                continue
            normalized = name.strip().lower()
            if normalized in RESERVED_AGENT_NAMES:
                errors.append(
                    StaticTypeError(
                        message=f"Action name '{name}' is reserved and cannot be used",
                        location=FieldLocation(agent_name=name, config_field="name"),
                        referenced_agent=name,
                        referenced_field="",
                        hint="Rename the action to avoid reserved namespaces.",
                    )
                )
        return errors

    def _check_context_scope_fields(self) -> list[StaticTypeError]:
        """Validate context_scope field references against dependency schemas.

        Checks that fields referenced in context_scope.observe and context_scope.passthrough
        actually exist in the dependency's output schema.

        Returns:
            List of StaticTypeError for invalid field references
        """
        from agent_actions.prompt.context.scope_parsing import (
            extract_action_names_from_context_scope,
        )

        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            context_scope = action.get("context_scope", {})

            if not context_scope:
                continue

            # Get action's dependencies (explicit + context_scope-inferred).
            # The runtime infers deps from context_scope refs, so validation must match.
            deps_list = action.get("depends_on") or action.get("dependencies", [])
            dependencies = set()
            if isinstance(deps_list, list):
                for dep in deps_list:
                    if isinstance(dep, str):
                        dependencies.add(dep)
            inferred = extract_action_names_from_context_scope(context_scope)
            dependencies |= {ns for ns in inferred if ns not in SPECIAL_NAMESPACES}

            # Check observe and passthrough directives
            for directive in ["observe", "passthrough"]:
                field_refs = context_scope.get(directive, [])
                if not isinstance(field_refs, list):
                    continue

                for field_ref in field_refs:
                    if not isinstance(field_ref, str):
                        continue

                    # Parse field reference: "dep_name.field_name" or "dep_name.*"
                    if "." not in field_ref:
                        continue  # Skip malformed references

                    parts = field_ref.split(".", 1)
                    dep_name = parts[0]
                    field_name = parts[1] if len(parts) > 1 else ""

                    # Skip special namespaces and loop (runtime namespace
                    # not in SPECIAL_NAMESPACES but valid in context_scope)
                    if dep_name in SPECIAL_NAMESPACES or dep_name == "loop":
                        continue

                    # Check if dependency is declared
                    if dep_name not in dependencies:
                        errors.append(
                            StaticTypeError(
                                message=f"context_scope.{directive} references undeclared dependency '{dep_name}'",
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=field_ref,
                                ),
                                referenced_agent=dep_name,
                                referenced_field=field_name,
                                hint=f"Add '{dep_name}' to dependencies or remove this reference.",
                            )
                        )
                        continue

                    # Validate field exists in dependency's output schema
                    dep_node = self.graph.get_node(dep_name)
                    if not dep_node:
                        errors.append(
                            StaticTypeError(
                                message=f"context_scope.{directive} references unknown action '{dep_name}'",
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=field_ref,
                                ),
                                referenced_agent=dep_name,
                                referenced_field=field_name,
                                hint=f"No action named '{dep_name}' exists in this workflow. Check for typos.",
                            )
                        )
                        continue

                    output_schema = dep_node.output_schema
                    if output_schema.is_dynamic:
                        if output_schema.load_error:
                            errors.append(
                                StaticTypeError(
                                    message=(
                                        f"Cannot validate context_scope.{directive} "
                                        f"field '{field_name}' — {output_schema.load_error}"
                                    ),
                                    location=FieldLocation(
                                        agent_name=action_name,
                                        config_field=f"context_scope.{directive}",
                                        raw_reference=field_ref,
                                    ),
                                    referenced_agent=dep_name,
                                    referenced_field=field_name,
                                    hint="Fix the schema file first, then re-run validation.",
                                )
                            )
                        continue

                    available_fields = output_schema.available_fields
                    if field_name not in available_fields:
                        errors.append(
                            StaticTypeError(
                                message=f"context_scope.{directive} references non-existent field '{field_name}' in '{dep_name}'",
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=field_ref,
                                ),
                                referenced_agent=dep_name,
                                referenced_field=field_name,
                                available_fields=available_fields,
                                hint=f"Check the output schema of '{dep_name}' for available fields.",
                            )
                        )

        return errors

    def _check_seed_reference_misuse(self) -> list[StaticTypeError]:
        """Catch common misuse of seed_data/seed_path in context_scope references.

        Users sometimes write ``seed_data.field`` or ``seed_path.field`` in
        observe/drop/passthrough when they should write ``seed.field``.
        """
        errors: list[StaticTypeError] = []
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")
            context_scope = action.get("context_scope", {})
            if not context_scope:
                continue

            for directive in ["observe", "drop", "passthrough", "drops"]:
                field_refs = context_scope.get(directive, [])
                if not isinstance(field_refs, list):
                    continue

                for field_ref in field_refs:
                    if not isinstance(field_ref, str) or "." not in field_ref:
                        continue

                    namespace, field_name = field_ref.split(".", 1)
                    if namespace in SEED_CONFIG_KEYS:
                        correct_ref = f"seed.{field_name}"
                        errors.append(
                            StaticTypeError(
                                message=(
                                    f"context_scope.{directive} references "
                                    f"'{field_ref}' — use '{correct_ref}' instead. "
                                    f"'{namespace}' is a config key for declaring file paths; "
                                    f"use the 'seed' namespace for runtime references."
                                ),
                                location=FieldLocation(
                                    agent_name=action_name,
                                    config_field=f"context_scope.{directive}",
                                    raw_reference=field_ref,
                                ),
                                referenced_agent=namespace,
                                referenced_field=field_name,
                                hint=f"Replace '{field_ref}' with '{correct_ref}'.",
                            )
                        )

        return errors

    def _check_schema_structures(self) -> list[StaticTypeError]:
        """Validate schema definitions for structural correctness.

        Pre-flight validation that catches schema issues before LLM execution:
        - Empty or invalid schema structures
        - Missing required field definitions
        - Invalid type specifications
        - Array schemas without items definition

        Returns:
            List of StaticTypeError for invalid schema structures
        """
        errors: list[StaticTypeError] = []
        validator = SchemaStructureValidator()
        actions = self.workflow_config.get("actions", [])

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_name = action.get("name", "unknown")

            # Check inline schema
            schema = action.get("schema")
            if schema and isinstance(schema, dict):
                schema_errors = validator.validate_schema(schema, action_name, "schema")
                errors.extend(schema_errors)

        return errors

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
                                    f"add '{dep_name}' to dependencies."
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

    def _check_guard_nullable_fields(self) -> list[StaticTypeWarning]:
        """Detect fields that may be None due to upstream guard filtering.

        When an action has ``guard.on_false`` set to ``"filter"`` or ``"skip"``,
        its output fields will be ``None`` for records that fail the guard.  If a
        downstream **tool** action observes those fields and its output schema
        declares a non-nullable type (e.g. ``type: object``), the workflow will
        crash at runtime with a schema validation error.

        Covers both direct observation (tool observes ``guarded.field``) and
        transitive passthrough (tool observes ``intermediate.field`` where
        ``intermediate`` passthroughs from a guarded action).

        This check is a **warning** (not an error) because:
        - The tool implementation may handle ``None`` internally.
        - The guard condition may never actually filter in practice.
        - The field may be populated from a different source in the fan-in.
        """
        warnings: list[StaticTypeWarning] = []
        actions = self.workflow_config.get("actions", [])

        # Step 1: Identify guarded actions with filter/skip behavior and their fields.
        guarded_actions: dict[str, dict[str, str]] = {}  # name -> {condition, behavior}
        guarded_fields: dict[str, set[str]] = {}  # name -> output field names
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = action.get("name", "")
            guard = action.get("guard")
            if not guard:
                continue

            if isinstance(guard, dict):
                condition = guard.get("condition", str(guard))
                behavior = guard.get("on_false", "filter")
            elif isinstance(guard, str):
                condition = guard
                behavior = "filter"  # string guards default to filter
            else:
                continue

            if behavior in ("filter", "skip"):
                guarded_actions[name] = {"condition": condition, "behavior": behavior}
                node = self.graph.get_node(name)
                if node:
                    guarded_fields[name] = node.output_schema.schema_fields.copy()

        if not guarded_actions:
            return warnings

        # Step 2: For each downstream tool, trace observe refs back to guarded
        #         actions — both direct and via passthrough intermediates.
        for action in actions:
            if not isinstance(action, dict):
                continue

            consumer_name = action.get("name", "unknown")
            consumer_node = self.graph.get_node(consumer_name)
            if not consumer_node:
                continue

            # Only tool actions have strict output schema validation.
            if consumer_node.agent_kind != ActionKind.TOOL:
                continue

            context_scope = action.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue

            observe_refs = context_scope.get("observe", [])
            if not isinstance(observe_refs, list):
                continue

            # Build a map: guarded_source -> set of observed field names.
            # Includes both direct refs and transitive passthrough refs.
            observed_from_guarded: dict[str, set[str]] = {}
            for ref in observe_refs:
                if not isinstance(ref, str) or "." not in ref:
                    continue
                source_name, field_name = ref.split(".", 1)
                if field_name == "*":
                    continue

                # Case 1: Direct observation of a guarded action.
                if source_name in guarded_actions:
                    observed_from_guarded.setdefault(source_name, set()).add(field_name)
                    continue

                # Case 2: Transitive — source is an intermediate that
                # passthroughs from a guarded action.
                source_node = self.graph.get_node(source_name)
                if not source_node:
                    continue
                source_output = source_node.output_schema
                for g_name in guarded_actions:
                    if g_name not in source_node.dependencies:
                        continue
                    # Wildcard passthrough: "G.*" → all of G's fields flow through
                    if g_name in source_output.passthrough_wildcard_sources:
                        if field_name in guarded_fields.get(g_name, set()):
                            observed_from_guarded.setdefault(g_name, set()).add(field_name)
                    # Specific passthrough: field_name matches a guarded field
                    elif field_name in source_output.passthrough_fields:
                        if field_name in guarded_fields.get(g_name, set()):
                            observed_from_guarded.setdefault(g_name, set()).add(field_name)

            if not observed_from_guarded:
                continue

            # Look up the consumer's output schema to find field type declarations.
            consumer_schema = consumer_node.output_schema.json_schema
            if not consumer_schema:
                continue

            # Build field_name -> declared_type from the schema.
            schema_field_types = self._extract_field_types_from_schema(consumer_schema)
            if not schema_field_types:
                continue

            # Step 3: Emit warnings for non-nullable fields sourced from guarded actions.
            for source_name, fields in observed_from_guarded.items():
                guard_info = guarded_actions[source_name]
                for field_name in sorted(fields):
                    declared_type = schema_field_types.get(field_name)
                    if declared_type is None:
                        continue  # Field not declared in consumer schema — no risk.
                    if self._type_allows_null(declared_type):
                        continue

                    warnings.append(
                        StaticTypeWarning(
                            message=(
                                f"Field '{field_name}' in tool action '{consumer_name}' "
                                f"may be None when guarded action '{source_name}' filters "
                                f"(guard: {guard_info['condition']}, "
                                f"on_false: {guard_info['behavior']}). "
                                f"Schema declares type '{declared_type}' which rejects None."
                            ),
                            location=FieldLocation(
                                agent_name=consumer_name,
                                config_field="schema",
                                raw_reference=f"{source_name}.{field_name}",
                            ),
                            referenced_agent=source_name,
                            referenced_field=field_name,
                            hint=(
                                f"Either remove '{field_name}' from the schema, "
                                f"or handle None in the tool implementation before returning."
                            ),
                        )
                    )

        return warnings

    @staticmethod
    def _extract_field_types_from_schema(schema: dict[str, Any] | list) -> dict[str, str]:
        """Extract {field_name: type_string} from a JSON schema or list-style schema."""
        result: dict[str, str] = {}

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

    @staticmethod
    def _type_allows_null(declared_type: str | list) -> bool:
        """Return True if the declared type explicitly allows null values."""
        if isinstance(declared_type, list):
            return "null" in declared_type
        return declared_type == "null"

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

    def _add_source_node(self) -> None:
        """Add the special source node for workflow input."""
        if self.source_schema:
            # Extract fields from provided source schema
            fields = self.schema_extractor.extract_fields_from_json_schema(self.source_schema)
            schema = OutputSchema(schema_fields=fields)
        else:
            # Source is dynamic - can have any fields
            schema = OutputSchema(is_dynamic=True)

        node = DataFlowNode(
            name="source",
            agent_kind=ActionKind.SOURCE,
            output_schema=schema,
        )
        self.graph.add_node(node)

    def _add_agent_node(self, action_config: dict[str, Any]) -> None:
        """Add an action node to the graph."""
        name = action_config.get("name", "unknown")

        # Determine action type
        kind = action_config.get("kind", DEFAULT_ACTION_KIND)
        model_vendor = action_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            agent_kind = ActionKind.TOOL
        elif kind == "hitl" or model_vendor == "hitl":
            agent_kind = ActionKind.HITL
        else:
            agent_kind = ActionKind.LLM

        # Extract output schema
        output_schema = self.schema_extractor.extract_schema(action_config, self.schema_loader)

        # Extract input schema (pass reference_extractor for LLM template analysis)
        input_schema = self.schema_extractor.extract_input_schema(
            action_config, self.reference_extractor
        )

        # Extract input requirements (field references)
        input_requirements = self.reference_extractor.extract_from_agent(action_config)

        # Use auto-inferred dependency model
        from agent_actions.prompt.context.scope_inference import infer_dependencies

        workflow_actions = [
            a.get("name") for a in self.workflow_config.get("actions", []) if a.get("name")
        ]

        try:
            input_sources, context_sources = infer_dependencies(
                action_config, workflow_actions, name
            )
            # All dependencies (both input and context) for graph building
            dependencies = set(input_sources + context_sources)
        except (ConfigurationError, KeyError, ValueError) as e:
            logger.warning("Dependency inference failed for '%s': %s", name, e, exc_info=True)
            deps_list = action_config.get("depends_on") or action_config.get("dependencies", [])
            dependencies = set()
            if isinstance(deps_list, str):
                dependencies.add(deps_list)
            elif isinstance(deps_list, list):
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

    def get_agent_schema(self, agent_name: str) -> OutputSchema | None:
        """Get the output schema for a specific action.

        Args:
            agent_name: Name of the action

        Returns:
            OutputSchema or None if action not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.output_schema if node else None

    def get_agent_input_schema(self, agent_name: str) -> InputSchema | None:
        """Get the input schema for a specific action.

        Args:
            agent_name: Name of the action

        Returns:
            InputSchema or None if action not found
        """
        if not self._built:
            self._build_graph()

        node = self.graph.get_node(agent_name)
        return node.input_schema if node else None

    def get_action_schemas(self) -> dict[str, dict[str, Any]]:
        """Get input and output schemas for all actions.

        Returns a dictionary mapping action names to their schemas:
        {
            "action_name": {
                "kind": "llm" | "tool" | "hitl",
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

        result: dict[str, dict[str, Any]] = {}

        for name, node in self.graph.nodes.items():
            # Skip special namespaces
            if self.graph.is_special_namespace(name):
                continue

            action_info: dict[str, Any] = {
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

    def _format_input_schema(self, input_info: dict[str, Any]) -> list[str]:
        """Format input schema section as lines."""
        if input_info["is_template_based"]:
            return ["    (template-based - see field references)"]
        if input_info["is_dynamic"]:
            return ["    (dynamic - determined at runtime)"]

        lines = []
        if input_info["required"]:
            lines.append(f"    required: {', '.join(input_info['required'])}")
        if input_info["optional"]:
            lines.append(f"    optional: {', '.join(input_info['optional'])}")
        if not lines:
            lines.append("    (no fields)")
        return lines

    def _format_output_schema(self, output_info: dict[str, Any]) -> list[str]:
        """Format output schema section as lines."""
        if output_info["is_schemaless"]:
            return ["    (schemaless - freeform output)"]
        if output_info["is_dynamic"]:
            return ["    (dynamic - determined at runtime)"]
        if output_info["fields"]:
            return [f"    fields: {', '.join(output_info['fields'])}"]
        return ["    (no fields)"]

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
            lines.extend(self._format_input_schema(info["input"]))
            lines.append("  Output:")
            lines.extend(self._format_output_schema(info["output"]))

        return "\n".join(lines)

    def _get_execution_order(self) -> list[str]:
        """Get execution order, falling back to node keys if cycle detected."""
        try:
            return self.graph.topological_sort()
        except ValueError:
            return list(self.graph.nodes.keys())

    def _build_agent_references(self, node: DataFlowNode) -> list[dict[str, str]]:
        """Build references list for an action node."""
        return [
            {"agent": req.source_agent, "field": req.field_path}
            for req in node.input_requirements
            if req.source_agent not in SPECIAL_NAMESPACES
        ]

    def _build_agent_info(self, node: DataFlowNode) -> dict[str, Any]:
        """Build action info dictionary for a node."""
        return {
            "name": node.name,
            "kind": node.agent_kind.value,
            "output_fields": sorted(node.output_schema.available_fields),
            "dependencies": sorted(node.dependencies),
            "references": self._build_agent_references(node),
        }

    def get_data_flow_summary(self) -> dict[str, Any]:
        """Get a summary of data flow in the workflow.

        Returns:
            Dict with nodes, edges, and execution order
        """
        if not self._built:
            self._build_graph()

        execution_order = self._get_execution_order()

        return {
            "agents": [
                self._build_agent_info(node)
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
        udf_registry: dict[str, Any] | None = None,
        schema_loader: Any | None = None,
    ) -> "WorkflowStaticAnalyzer":
        """Create analyzer from workflow file path.

        Args:
            workflow_path: Path to workflow YAML file
            udf_registry: UDF_REGISTRY for tool schema lookup
            schema_loader: SchemaLoader for external schemas

        Returns:
            Configured WorkflowStaticAnalyzer
        """
        import yaml

        with open(workflow_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        return cls(config, udf_registry=udf_registry, schema_loader=schema_loader)


def analyze_workflow(
    workflow_config: dict[str, Any],
    udf_registry: dict[str, Any] | None = None,
    schema_loader: Any | None = None,
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
