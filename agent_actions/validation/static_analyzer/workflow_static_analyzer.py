"""Main workflow static analyzer that orchestrates all components.

Provides a unified interface for static type checking of workflow configurations,
similar to TypeScript's compile-time type checking.
"""

import logging
import re as re
from typing import Any

from jinja2.exceptions import TemplateSyntaxError

from agent_actions.errors import ConfigurationError
from agent_actions.guards.bare_reference import spreads_output_flat
from agent_actions.guards.consolidated_guard import GuardBehavior as GuardBehavior
from agent_actions.input.context.normalizer import SEED_CONFIG_KEYS as SEED_CONFIG_KEYS
from agent_actions.input.context.normalizer import normalize_context_scope
from agent_actions.output.response.config_fields import get_default as get_default
from agent_actions.output.response.expander_validation import routing_kind
from agent_actions.prompt.aliases import header_names as header_names
from agent_actions.record.elsewhere import gathers as gathers
from agent_actions.record.elsewhere import sends_elsewhere as sends_elsewhere
from agent_actions.utils.constants import DEFAULT_ACTION_KIND as DEFAULT_ACTION_KIND
from agent_actions.utils.constants import JSON_MODE_KEY as JSON_MODE_KEY
from agent_actions.utils.constants import RESERVED_AGENT_NAMES
from agent_actions.utils.constants import SCHEMA_KEY as SCHEMA_KEY
from agent_actions.utils.constants import SCHEMA_NAME_KEY as SCHEMA_NAME_KEY
from agent_actions.utils.constants import SPECIAL_NAMESPACES as SPECIAL_NAMESPACES

from .cache_checks import PromptCacheChecksMixin
from .data_flow_graph import (
    ActionKind,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    OutputSchema,
)
from .data_flow_graph import InputSchema as InputSchema
from .errors import FieldLocation, StaticTypeError, StaticValidationResult
from .errors import StaticTypeWarning as StaticTypeWarning
from .file_mode_checks import FileModeChecksMixin
from .graph_reporting import GraphReportingMixin
from .guard_checks import GuardChecksMixin, guard_clause_and_behavior
from .lineage_checks import LineageChecksMixin
from .reference_extractor import ReferenceExtractor
from .schema_checks import SchemaChecksMixin
from .schema_extractor import SchemaExtractor
from .schema_structure_validator import SchemaStructureValidator as SchemaStructureValidator
from .scope_checks import ContextScopeChecksMixin
from .type_checker import StaticTypeChecker

logger = logging.getLogger(__name__)


class WorkflowStaticAnalyzer(
    ContextScopeChecksMixin,
    FileModeChecksMixin,
    SchemaChecksMixin,
    GuardChecksMixin,
    LineageChecksMixin,
    PromptCacheChecksMixin,
    GraphReportingMixin,
):
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
        2. Referenced actions are declared in dependencies
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
        self._build_errors: list[StaticTypeError] = []

    def analyze(self) -> StaticValidationResult:
        """Perform static analysis of the workflow.

        Returns:
            StaticValidationResult with errors and warnings
        """
        # Step 0: Validate context_scope BEFORE normalization so diagnostic
        # hints can inspect the raw YAML values (null, wrong type, orphaned
        # directives). Normalization in Step 0b converts null → {} which would
        # destroy the diagnostic signal.
        context_scope_errors = self._check_context_scope_required()

        # Step 0b: Normalize context_scope (same function the runtime uses) so
        # extractors see a dict. A removed directive raises here; collect it as a
        # validation error rather than letting analyze() abort mid-pass.
        for action in self.workflow_config.get("actions", []):
            if isinstance(action, dict):
                try:
                    action["context_scope"] = normalize_context_scope(
                        action.get("context_scope"), version_base_map={}
                    )
                except ConfigurationError as exc:
                    context_scope_errors.append(
                        StaticTypeError(
                            message=str(exc),
                            location=FieldLocation(
                                agent_name=action.get("name", "workflow"),
                                config_field="context_scope",
                            ),
                            referenced_agent="",
                            referenced_field="",
                        )
                    )
                    action["context_scope"] = {}

        # Guard-skip observe warnings must be computed before wildcard expansion
        # because expansion turns safe wildcards into specific refs (false positives).
        guard_skip_observe_warnings = self._check_guard_skipped_observe_refs()

        # Guard-filter + fan-in observe hazard: also before wildcard expansion.
        filter_fanin_warnings = self._check_filter_fanin_observe_hazard()

        # FILE-tool observe collision: also before expansion, since two wildcard
        # namespaces qualify every flat key and expansion would hide that.
        file_tool_collision_warnings = self._check_file_tool_observe_collision()

        # Step 1: Build data flow graph
        self._build_graph()

        # Step 1b: Check for circular dependencies
        cycle_errors: list[StaticTypeError] = []
        try:
            self.graph.topological_sort()
        except ValueError as exc:
            workflow_name = self.workflow_config.get("name", "workflow")
            cycle_errors.append(
                StaticTypeError(
                    message=str(exc),
                    location=FieldLocation(
                        agent_name=workflow_name,
                        config_field="dependencies",
                    ),
                    referenced_agent="",
                    referenced_field="",
                )
            )

        # Step 2: Expand wildcard field references (namespace.* → concrete fields)
        expansion_errors = self._expand_wildcards()

        # Step 3: Run type checker
        checker = StaticTypeChecker(self.graph)
        result = checker.check_all()

        for error in cycle_errors:
            result.add_error(error)
        for error in self._build_errors:
            result.add_error(error)
        for error in expansion_errors:
            result.add_error(error)

        # Step 3b: Reserved action name validation
        for error in self._check_reserved_action_names():
            result.add_error(error)

        # Step 3b-2: FILE granularity needs an upstream action to read a file of
        for error in self._check_first_stage_file_granularity():
            result.add_error(error)

        for error in self._check_named_schemas_load():
            result.add_error(error)

        # Step 3c: context_scope validation (already ran in Step 0 before normalization)
        for error in context_scope_errors:
            result.add_error(error)

        # Step 3d: Validate template namespaces are covered by context_scope
        for error in self._check_template_scope_coverage():
            result.add_error(error)

        # Step 2d: Catch seed_data/seed_path misuse in context_scope references
        for error in self._check_seed_reference_misuse():
            result.add_error(error)

        # Step 2d-2: Warn when a seed field is both observed and template-referenced
        for warning in self._check_seed_template_observe_overlap():
            result.add_warning(warning)

        # Step 2e: Validate schema structures (pre-flight check)
        for error in self._check_schema_structures():
            result.add_error(error)

        # Step 2f: Validate drop directives target schema/observe fields
        drop_errors, drop_warnings = self._check_drop_directives()
        for error in drop_errors:
            result.add_error(error)
        for warning in drop_warnings:
            result.add_warning(warning)

        # Step 2h: Guard literals whose type can never match the field's schema type
        for warning in self._check_guard_literal_type_mismatch():
            result.add_warning(warning)

        for warning in guard_skip_observe_warnings:
            result.add_warning(warning)

        for warning in filter_fanin_warnings:
            result.add_warning(warning)

        for warning in file_tool_collision_warnings:
            result.add_warning(warning)

        # Step 3: Check for unused dependencies (add as warnings)
        for warning in checker.check_unused_dependencies():
            result.add_warning(warning)

        # Step 3b: Check lineage reachability for observe/passthrough references
        for warning in self._check_lineage_reachability():
            result.add_warning(warning)

        # Step 5: Warn when json_mode=false but schema is defined
        for warning in self._check_json_mode_schema_mismatch():
            result.add_warning(warning)

        for warning in self._check_prompt_caching_on_record_data():
            result.add_warning(warning)

        cache_point_errors, cache_point_warnings = self._check_cache_points()
        for error in cache_point_errors:
            result.add_error(error)
        for warning in cache_point_warnings:
            result.add_warning(warning)

        return result

    def _build_graph(self) -> None:
        """Build the data flow graph from workflow config."""
        if self._built:
            return

        actions = self.workflow_config.get("actions", [])

        # Every reader below expects a mapping, which the lazy entry points reaching here
        # do not guarantee the way `analyze()` does (#1193). Copied, not written back:
        # Step 0 picks its hint from the raw value, which overwriting would destroy.
        actions = [
            {**action, "context_scope": {}}
            if isinstance(action, dict) and not isinstance(action.get("context_scope"), dict)
            else action
            for action in actions
        ]

        # Add special source node (always available)
        self._add_source_node()

        # Add action nodes from actions
        for action_config in actions:
            try:
                self._add_agent_node(action_config)
            except TemplateSyntaxError as exc:
                action_name = action_config.get("name", "unknown")
                self._build_errors.append(
                    StaticTypeError(
                        message=f"Template syntax error in '{action_name}': {exc.message} "
                        f"(line {exc.lineno})",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field="prompt",
                            line_number=exc.lineno,
                        ),
                        referenced_agent=action_name,
                        referenced_field="",
                    )
                )

        # Build edges from input requirements
        self.graph.build_edges_from_requirements()

        self._built = True

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
        kind = routing_kind(action_config)

        if kind == "tool":
            agent_kind = ActionKind.TOOL
        elif kind == "hitl":
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
        input_requirements = self._without_guard_promotions(
            action_config, self.reference_extractor.extract_from_agent(action_config)
        )

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
            deps_list = action_config.get("dependencies", [])
            dependencies = set()
            if isinstance(deps_list, str):
                dependencies.add(deps_list)
            elif isinstance(deps_list, list):
                for dep in deps_list:
                    if isinstance(dep, str):
                        dependencies.add(dep)

        node = DataFlowNode(
            name=name,
            agent_kind=agent_kind,
            output_schema=output_schema,
            input_schema=input_schema,
            input_requirements=input_requirements,
            dependencies=dependencies,
        )

        self.graph.add_node(node)

    def _without_guard_promotions(
        self, action_config: dict[str, Any], requirements: list[InputRequirement]
    ) -> list[InputRequirement]:
        """Drop guard reads of a name a dependency puts at the top of the guard context.

        `build_guard_context` promotes each dependency's `output_field`, and a
        FILE-granularity version-merge tool spreads its output flat over the record, so
        any name may be one of its fields. Neither is an action, and neither is provably
        absent, so neither is checked as one.
        """
        if not any(req.location == "guard" for req in requirements):
            return requirements
        configs = {
            a.get("name"): a
            for a in self.workflow_config.get("actions", [])
            if isinstance(a, dict)
        }
        declared = action_config.get("dependencies") or []
        if isinstance(declared, str):
            declared = [declared]
        upstreams = [configs[d] for d in declared if isinstance(d, str) and d in configs]
        if any(spreads_output_flat(up) for up in upstreams):
            return [req for req in requirements if req.location != "guard"]
        promoted = {up.get("output_field") for up in upstreams} - {None}
        return [
            req
            for req in requirements
            if not (req.location == "guard" and req.source_agent in promoted)
        ]

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


# ── Guard-nullable schema auto-fix ──────────────────────────────────


def _make_schema_field_nullable(schema: dict[str, Any], field_name: str) -> bool:
    """Add ``"null"`` to a field's type in a JSON Schema dict.

    Handles standard ``properties`` format, ``items.properties`` (array schema),
    and nested ``schema`` wrapper.  Returns ``True`` if the field was modified.
    """
    # Standard properties format
    properties = schema.get("properties")
    if isinstance(properties, dict) and field_name in properties:
        field_def = properties[field_name]
        if isinstance(field_def, dict) and "type" in field_def:
            field_type = field_def["type"]
            if isinstance(field_type, str) and field_type != "null":
                field_def["type"] = [field_type, "null"]
                return True
            if isinstance(field_type, list) and "null" not in field_type:
                field_type.append("null")
                return True

    # Array items.properties format
    items = schema.get("items")
    if isinstance(items, dict):
        if _make_schema_field_nullable(items, field_name):
            return True

    # Nested schema wrapper (e.g. OpenAI compiled)
    nested = schema.get("schema")
    if isinstance(nested, dict):
        if _make_schema_field_nullable(nested, field_name):
            return True

    return False


def apply_guard_nullable_schema_fixes(
    action_configs: dict[str, dict[str, Any]],
) -> list[str]:
    """Make guard-nullable fields accept ``null`` in downstream ``json_output_schema``.

    When upstream actions have ``guard.on_false`` set to ``"filter"`` or
    ``"skip"``, downstream tool actions that observe those fields may receive
    ``None`` at runtime.  This function modifies ``json_output_schema`` **in
    place** so that ``jsonschema.validate()`` accepts ``null`` for those fields.

    The null is carried forward: a tool that observes a field which may be null, and
    returns a field of the same name, may return null there too (a relay of a skipped
    action's field), so a tool observing that one is fixed as well. Carried through each
    such tool until nothing changes, so the order of ``action_configs`` does not matter.

    Call this after schema compilation and static validation but before
    workflow execution.

    Returns:
        List of fixed field paths (e.g. ``["consumer.field"]``).
    """
    fixes: list[str] = []

    # Fields each action may leave null; None means every field (a guarded action).
    may_be_null: dict[str, set[str] | None] = {}
    for name, config in action_configs.items():
        read = guard_clause_and_behavior(config.get("guard"))
        if read is not None and read[1] in ("filter", "skip"):
            may_be_null[name] = None

    if not may_be_null:
        return fixes

    consumers: list[tuple[str, dict[str, Any], list[tuple[str, str]]]] = []
    for consumer_name, consumer_config in action_configs.items():
        if consumer_config.get("kind") != "tool":
            continue
        json_schema = consumer_config.get("json_output_schema")
        context_scope = consumer_config.get("context_scope")
        if not isinstance(json_schema, dict) or not isinstance(context_scope, dict):
            continue
        observe_refs = context_scope.get("observe", [])
        if not isinstance(observe_refs, list):
            continue
        reads = [
            (source, field)
            for source, _, field in (
                ref.partition(".") for ref in observe_refs if isinstance(ref, str) and "." in ref
            )
            if field != "*"
        ]
        if reads:
            consumers.append((consumer_name, json_schema, reads))

    changed = True
    while changed:
        changed = False
        for consumer_name, json_schema, reads in consumers:
            nullable_reads = set()
            for source, field in reads:
                if source not in may_be_null:
                    continue
                fields = may_be_null[source]
                if fields is None or field in fields:
                    nullable_reads.add(field)
            for field_name in sorted(nullable_reads):
                if _make_schema_field_nullable(json_schema, field_name):
                    fixes.append(f"{consumer_name}.{field_name}")
            if may_be_null.get(consumer_name, set()) is None:
                continue
            returned = set(WorkflowStaticAnalyzer._extract_field_types_from_schema(json_schema))
            carried = nullable_reads & returned
            known = may_be_null.setdefault(consumer_name, set())
            if known is not None and not carried <= known:
                known |= carried
                changed = True

    return fixes
