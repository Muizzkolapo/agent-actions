"""
Context Scope Processor - Field flow control for LLM context and output.

Processes context_scope directives: static_data, observe, drop, passthrough.
"""
# Line-too-long: Complex data transformations require descriptive variable names
# Import-outside-toplevel: Avoid circular imports
# Broad-exception-caught: Intentional fallback behavior for data processing

import json
import logging
from collections import Counter
from typing import Dict, List, Tuple, Any, Optional, TYPE_CHECKING
from copy import deepcopy

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

from agent_actions.errors import ConfigurationError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import (
    ContextFieldSkippedEvent,
    ContextNamespaceLoadedEvent,
    ContextScopeAppliedEvent,
    ContextDependencyInferredEvent,
)
from agent_actions.utils.constants import SPECIAL_NAMESPACES
from agent_actions.utils.dict import get_nested_value, nested_field_exists, set_nested_value

logger = logging.getLogger(__name__)


class ContextScopeProcessor:
    """
    Processes context_scope configuration for field flow control.

    Special Namespaces:
        source: Original input data loaded from source files
        version: Current iteration context in versioned actions (i, idx, length, first, last)
        workflow: Workflow metadata (name, version, run_id)
    """

    @staticmethod
    def parse_field_reference(field_ref: str) -> Tuple[str, str]:
        """
        Parse field reference in 'action.field' format, returning (action_name, field_name).

        Also handles loop field prefix patterns (e.g., 'extract_raw_qa_') which indicate
        fields from all loop iterations. For these patterns, returns (base_name, '_')
        where '_' signals a field prefix pattern.
        """
        if not field_ref or not isinstance(field_ref, str):
            raise ValueError(
                f"Invalid field reference: {field_ref!r}. "
                f"Expected non-empty string in format 'action.field' or field prefix pattern ending with '_'"
            )

        # Check if this is a field prefix pattern (ends with _ but no dot)
        # e.g., "extract_raw_qa_" for loop consumption
        if field_ref.endswith("_") and "." not in field_ref:
            # Field prefix pattern - return base name and '_' marker
            base_name = field_ref[:-1]  # Remove trailing underscore
            if not base_name:
                raise ValueError(
                    f"Invalid field prefix pattern: '{field_ref}'. Base name cannot be empty"
                )
            return (base_name, "_")

        parts = field_ref.split(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid field reference: '{field_ref}'. "
                f"Expected format: 'action.field' (with exactly one dot) or field prefix pattern ending with '_'"
            )

        action_name, field_name = parts

        if not action_name or not field_name:
            raise ValueError(
                f"Invalid field reference: '{field_ref}'. Both action and field must be non-empty"
            )

        return (action_name, field_name)

    @staticmethod
    def extract_field_names_from_references(
        field_refs: List[str], _return_type: str = "list"
    ) -> List[str]:
        """
        Extract field names from list of field references.

        Args:
            field_refs: List of references in 'action.field' format
            _return_type: Return type ('list' or other - currently only 'list' supported)

        Returns:
            List of field names extracted from references

        Example:
            ['generate_summary.key_concepts', 'extract.facts'] -> ['key_concepts', 'facts']
        """
        field_names = []

        for field_ref in field_refs:
            try:
                _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                field_names.append(field_name)
            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name="unknown",
                        field_ref=field_ref,
                        reason=str(e),
                        directive="extract_field_names",
                    )
                )
                continue

        return field_names

    @staticmethod
    def extract_action_names_from_context_scope(context_scope: Optional[Dict]) -> set:
        """
        Extract unique action names referenced in context_scope.

        Parses observe and passthrough fields to find all action names.

        Args:
            context_scope: Context scope configuration dict

        Returns:
            Set of action names referenced in context_scope

        Example:
            context_scope = {
                "observe": ["add_answer_text.*", "suggest_distractor_counts.target_word_counts"],
                "passthrough": ["write_scenario_question.question"]
            }
            Returns: {"add_answer_text", "suggest_distractor_counts", "write_scenario_question"}
        """
        if not context_scope:
            return set()

        referenced_actions = set()

        # Collect field references from observe and passthrough
        all_field_refs = []
        all_field_refs.extend(context_scope.get("observe", []))
        all_field_refs.extend(context_scope.get("passthrough", []))

        for field_ref in all_field_refs:
            try:
                action_name, _ = ContextScopeProcessor.parse_field_reference(field_ref)
                referenced_actions.add(action_name)
            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name="unknown",
                        field_ref=field_ref,
                        reason=str(e),
                        directive="extract_action_names",
                    )
                )
                continue

        return referenced_actions

    @staticmethod
    def extract_action_names_from_template(template: Optional[str]) -> set:
        """
        Extract unique action names referenced in a Jinja2 template.

        Parses template for {{ namespace.field }} patterns and extracts namespace names.
        Filters out special namespaces (source, version, workflow) and common Jinja2 filters.

        Args:
            template: Jinja2 template string

        Returns:
            Set of action names (potential upstream dependencies) referenced in template

        Example:
            template = "{{ summarize_page_content.summary }} and {{ source.text }}"
            Returns: {"summarize_page_content"}  # 'source' is filtered as special namespace
        """
        import re

        if not template or not isinstance(template, str):
            return set()

        referenced_actions = set()

        # Match {{ namespace.field }} or {{ namespace['field'] }} patterns
        # This regex captures the namespace (first identifier before . or [)
        pattern = r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[\.\[]"
        matches = re.findall(pattern, template)

        for namespace in matches:
            # Filter out special namespaces and common Jinja2 variables
            if namespace in SPECIAL_NAMESPACES:
                continue
            if namespace in ("loop", "range", "true", "false", "none", "self", "version"):
                continue
            referenced_actions.add(namespace)

        return referenced_actions

    @staticmethod
    def _get_base_name(action_name: str) -> str:
        """
        Strip trailing _N suffix to get base action name.

        Examples:
            'classify_1' → 'classify'
            'research_10' → 'research'
            'extract_raw_qa_2' → 'extract_raw_qa'
            'validate' → 'validate' (no suffix)
        """
        parts = action_name.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return action_name

    @staticmethod
    def _is_parallel_branches(dependencies: List[str]) -> bool:
        """
        Detect if dependencies are parallel branches of the same action.

        Parallel branches have the same base name with numeric suffixes:
        - ['classify_1', 'classify_2', 'classify_3'] → True (all 'classify')
        - ['extract', 'enrich', 'validate'] → False (different actions)
        - ['classify'] → True (single = trivially parallel)

        Note: Different base names with same suffix are NOT parallel:
        - ['classify_text_1', 'classify_image_1'] → False (different base names)

        Args:
            dependencies: List of dependency action names

        Returns:
            True if all dependencies are branches of same action, False if fan-in
        """
        if len(dependencies) <= 1:
            return True  # Single or empty is trivially "parallel"

        base_names = {ContextScopeProcessor._get_base_name(dep) for dep in dependencies}
        return len(base_names) == 1

    @staticmethod
    def _get_version_branches(base_name: str, dependencies: List[str]) -> List[str]:
        """
        Find all dependencies that are version branches of a base name.

        Examples:
            _get_version_branches('research', ['research_1', 'research_2', 'summarize'])
            → ['research_1', 'research_2']

            _get_version_branches('classify', ['classify_text_1', 'classify_image_1'])
            → []  (these have different base names)

        Args:
            base_name: The base action name to match
            dependencies: List of dependency action names

        Returns:
            List of dependencies that are versions of base_name
        """
        return [
            d
            for d in dependencies
            if d.startswith(f"{base_name}_") and d[len(base_name) + 1 :].isdigit()
        ]

    @staticmethod
    def _resolve_input_sources_for_fan_in(
        dependencies: List[str],
        primary_dependency: Optional[str] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Resolve which dependencies are input sources vs context sources for fan-in pattern.

        This is the shared logic used by both infer_dependencies() and
        _resolve_dependency_directories() to avoid duplication.

        Args:
            dependencies: List of all dependency action names
            primary_dependency: Optional explicit primary override

        Returns:
            Tuple of (input_sources, context_sources)

        Raises:
            ValueError: If primary_dependency is invalid (not found in deps or as base name)
        """
        if primary_dependency is None:
            # No explicit primary - use first dependency
            # But if first dep is a version branch, include ALL sibling branches
            first_dep = dependencies[0]
            base_name = ContextScopeProcessor._get_base_name(first_dep)
            sibling_branches = ContextScopeProcessor._get_version_branches(base_name, dependencies)

            if sibling_branches and first_dep in sibling_branches:
                # First dep is a version branch - include all siblings as input
                input_sources = sibling_branches
            else:
                # First dep is not versioned - just use it
                input_sources = [first_dep]
        elif primary_dependency in dependencies:
            # Explicit primary exists in deps - check if it's versioned
            base_name = ContextScopeProcessor._get_base_name(primary_dependency)
            sibling_branches = ContextScopeProcessor._get_version_branches(base_name, dependencies)

            if sibling_branches and primary_dependency in sibling_branches:
                # Primary is a version branch - include all siblings
                input_sources = sibling_branches
            else:
                # Primary is not versioned - just use it
                input_sources = [primary_dependency]
        else:
            # Primary is a base name - expand to all version branches
            version_branches = ContextScopeProcessor._get_version_branches(
                primary_dependency, dependencies
            )
            if version_branches:
                input_sources = version_branches
            else:
                raise ValueError(
                    f"primary_dependency '{primary_dependency}' not found in "
                    f"dependencies list {dependencies} (also checked as base name)"
                )

        context_sources = [d for d in dependencies if d not in input_sources]
        return input_sources, context_sources

    @staticmethod
    def infer_dependencies(
        action_config: Dict, workflow_actions: List[str], action_name: str = "unknown"
    ) -> Tuple[List[str], List[str]]:
        """
        Infer input sources and context sources from action configuration.

        This method implements the simplified dependency model where:
        - `dependencies` field = input sources (determines execution count)
        - Actions in `context_scope` but NOT in `dependencies` = context sources (auto-inferred)

        Args:
            action_config: Action configuration dict containing dependencies and context_scope
            workflow_actions: List of all action names in the workflow (for validation)
            action_name: Name of current action (for error messages)

        Returns:
            Tuple of (input_sources, context_sources):
            - input_sources: List of actions that provide input files
            - context_sources: List of actions that provide context only (loaded via historical loader)

        Raises:
            ConfigurationError: If a referenced action doesn't exist in workflow

        Example:
            action_config = {
                "dependencies": "add_answer_text",
                "context_scope": {
                    "observe": [
                        "add_answer_text.*",
                        "suggest_distractor_counts.*",
                        "write_scenario_question.question"
                    ]
                }
            }
            workflow_actions = ["extract", "flatten", "add_answer_text", "suggest_distractor_counts", "write_scenario_question"]

            Returns:
                (["add_answer_text"], ["suggest_distractor_counts", "write_scenario_question"])
        """
        # 1. Get explicit dependencies (input sources)
        # Support both 'dependencies' and 'depends_on' for backward compatibility
        deps = action_config.get("dependencies") or action_config.get("depends_on", [])
        if deps is None:
            all_deps = []
        elif isinstance(deps, str):
            all_deps = [deps]
        else:
            all_deps = list(deps)

        # 1b. Handle fan-in pattern: multiple DIFFERENT dependencies
        # For fan-in, only the primary dependency is an input source
        # The rest become context sources (loaded via historical loader with lineage matching)
        #
        # Exception: If reduce_key is set, it's an aggregation pattern - all are input sources
        #
        # Versioned primary handling: If primary_dependency is a base name (e.g., "research")
        # that matches version branches (research_1, research_2), ALL matching branches
        # become input sources.
        fan_in_context_sources = []
        has_reduce_key = action_config.get("reduce_key") is not None
        is_parallel = ContextScopeProcessor._is_parallel_branches(all_deps)

        if len(all_deps) > 1 and not is_parallel and not has_reduce_key:
            # Fan-in detected - use shared helper
            primary_dep = action_config.get("primary_dependency")
            try:
                input_sources, fan_in_context_sources = (
                    ContextScopeProcessor._resolve_input_sources_for_fan_in(all_deps, primary_dep)
                )
            except ValueError as e:
                raise ConfigurationError(f"Action '{action_name}': {e}") from e

            logger.debug(
                f"Action '{action_name}': Fan-in detected with dependencies {all_deps}. "
                f"Input sources: {input_sources}. "
                f"Context sources (lineage-matched): {fan_in_context_sources}"
            )
        else:
            # Single dependency, parallel branches, or aggregation (reduce_key) - all are input sources
            input_sources = all_deps

        # 2. Parse context_scope to find all referenced actions
        context_scope = action_config.get("context_scope", {})
        referenced_actions = ContextScopeProcessor.extract_action_names_from_context_scope(
            context_scope
        )

        # 2a. Auto-infer from prompt template (if no context_scope configured)
        # This enables {{ upstream_action.field }} references to work without explicit context_scope
        from agent_actions.prompt.formatter import PromptFormatter

        try:
            raw_prompt = PromptFormatter.get_raw_prompt(action_config)
            if raw_prompt:
                template_actions = ContextScopeProcessor.extract_action_names_from_template(
                    raw_prompt
                )
                # Only add template-referenced actions that are valid workflow actions
                valid_template_actions = template_actions & set(workflow_actions)
                if valid_template_actions - referenced_actions:
                    logger.debug(
                        f"[TEMPLATE-INFER] Action '{action_name}': Auto-inferred context sources "
                        f"from template: {valid_template_actions - referenced_actions}"
                    )
                referenced_actions = referenced_actions | valid_template_actions
        except Exception:
            # If prompt retrieval fails, skip template-based inference
            pass

        # 2b. Identify field prefix patterns and wildcards from context_scope
        # Collect all field references once to avoid duplication
        field_prefix_base_names = set()
        wildcard_actions = set()
        all_field_refs = []
        all_field_refs.extend(context_scope.get("observe", []))
        all_field_refs.extend(context_scope.get("passthrough", []))
        for field_ref in all_field_refs:
            try:
                ref_action, ref_field = ContextScopeProcessor.parse_field_reference(field_ref)
                if ref_field == "_":  # Field prefix pattern
                    field_prefix_base_names.add(ref_action)
                elif ref_field == "*":  # Wildcard pattern
                    wildcard_actions.add(ref_action)
            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="infer_dependencies",
                    )
                )
                continue

        # 3. Auto-infer context sources (in context_scope but NOT in dependencies)
        # Also include fan-in context sources (non-primary dependencies from fan-in pattern)
        # NOTE: Do NOT exclude field prefix base names here. They are expanded later into
        # version variants so the caller can request all available branches. We will
        # de-duplicate against input_sources after expansion to avoid overwriting.
        potential_context_sources = (
            referenced_actions - set(input_sources) - set(fan_in_context_sources)
        )
        context_sources = list(fan_in_context_sources)  # Start with fan-in context sources
        for action in potential_context_sources:
            context_sources.append(action)

        # 4. Expand version base names to their variants (e.g., extract_raw_qa -> [extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3])
        # This handles version_consumption where context_scope references the base name
        def expand_version_base_names(
            action_list: List[str],
        ) -> List[str]:
            """Expand version base names to their actual variants in the workflow."""
            expanded = []
            for action in action_list:
                # Skip validation for version field prefix patterns (ending with _)
                # These are field prefix patterns from version_consumption merge, not action names
                # Example: "extract_raw_qa_" matches fields like "extract_raw_qa_1_questions"
                if action.endswith("_"):
                    expanded.append(action)
                    logger.debug(
                        f"[VERSION_FIELD_PREFIX] Keeping '{action}' as field prefix pattern (not an action)"
                    )
                    continue

                if action in workflow_actions:
                    # Action exists as-is
                    expanded.append(action)
                else:
                    # Check if this is a version base name
                    version_variants = [
                        wf_action
                        for wf_action in workflow_actions
                        if wf_action.startswith(f"{action}_")
                        and wf_action[len(action) + 1 :].isdigit()
                    ]
                    if version_variants:
                        # Expand to all variants. For context sources with wildcards, we still
                        # expand to concrete version names so they can be loaded via agent_indices.
                        expanded.extend(version_variants)
                        logger.debug(
                            f"[VERSION_EXPAND] Expanded version base name '{action}' to {version_variants}"
                        )
                    else:
                        # Not a version base name - keep as-is (will error in validation)
                        expanded.append(action)
            return expanded

        # Expand both input_sources and context_sources
        input_sources_expanded = expand_version_base_names(input_sources)
        context_sources_expanded = expand_version_base_names(context_sources)
        # Avoid loading context sources already provided via input sources.
        if input_sources_expanded:
            input_sources_set = set(input_sources_expanded)
            context_sources_expanded = [
                dep for dep in context_sources_expanded if dep not in input_sources_set
            ]

        # 5. Validate all referenced actions exist in workflow
        # Skip validation for field prefix patterns (ending with _) and special namespaces
        all_deps = set(input_sources_expanded) | set(context_sources_expanded)
        for dep_action in all_deps:
            # Skip validation for loop field prefix patterns
            if dep_action.endswith("_"):
                continue

            # Skip validation for special reserved namespaces (source, version, workflow, etc.)
            if dep_action in SPECIAL_NAMESPACES:
                continue

            if dep_action not in workflow_actions:
                raise ConfigurationError(
                    f"Action '{action_name}': References '{dep_action}' in dependencies/context_scope "
                    f"but '{dep_action}' not found in workflow.\n\n"
                    f"Available actions: {workflow_actions}",
                    context={
                        "action": action_name,
                        "missing_action": dep_action,
                        "workflow_actions": workflow_actions,
                        "input_sources": input_sources_expanded,
                        "context_sources": context_sources_expanded,
                    },
                )

        logger.debug(
            f"[INFER_DEPS] Action '{action_name}': "
            f"input_sources={input_sources_expanded}, context_sources={context_sources_expanded}"
        )

        # Fire event for successful inference
        fire_event(
            ContextDependencyInferredEvent(
                action_name=action_name,
                input_sources=input_sources_expanded,
                context_sources=context_sources_expanded,
            )
        )

        return input_sources_expanded, context_sources_expanded

    @staticmethod
    def extract_field_value(field_context: Dict, action_name: str, field_name: str) -> Any:
        """Extract field value from nested field_context structure, returning None if not found."""
        if not isinstance(field_context, dict):
            return None

        if action_name not in field_context:
            return None

        action_data = field_context[action_name]

        if not isinstance(action_data, dict):
            return None

        # Exact key match first (backward compat for flat fields and literal dotted keys)
        if field_name in action_data:
            return action_data[field_name]

        # Nested path traversal for dot-separated paths
        if "." in field_name:
            return get_nested_value(action_data, field_name)

        return None

    @staticmethod
    def extract_action_fields(field_context: Dict, action_name: str) -> Optional[Dict]:
        """Return all fields for an action if present and dict-like, otherwise None."""
        if not isinstance(field_context, dict):
            return None

        action_data = field_context.get(action_name)
        if not isinstance(action_data, dict):
            return None

        return action_data

    @staticmethod
    def apply_context_scope(
        field_context: Dict,
        context_scope: Dict,
        static_data: Optional[Dict] = None,
        action_name: str = "unknown",
    ) -> Tuple[Dict, Dict, Dict]:
        """
        Apply context_scope rules, returning (prompt_context, llm_context, passthrough_fields).

        Adds SEED namespace from static_data parameter (namespace #3 per anatomy_action.md).
        This is the 5th namespace that gets added to field_context before filtering.

        Args:
            field_context: Input context with {source, {dep_name}, version, workflow} namespaces
            context_scope: Dict with observe/passthrough/drop lists
            static_data: Optional seed data to add under 'seed' namespace
            action_name: Name of the action for event logging

        Returns:
            Tuple of (prompt_context, llm_context, passthrough_fields)
        """
        # Deep copy to avoid mutating original field_context
        prompt_context = deepcopy(field_context)
        llm_context = {}
        passthrough_fields = {}

        # Process STATIC_DATA: Add SEED namespace (namespace #3)
        if static_data:
            logger.debug(
                "[STATIC_DATA] Merging %s static data fields into context", len(static_data)
            )
            logger.debug("[STATIC_DATA] Fields: %s", list(static_data.keys()))

            # Add under 'seed' namespace in prompt_context (for field reference replacement)
            # This allows references like {{seed.exam_syllabus}} in prompts
            if "seed" in prompt_context:
                logger.warning(
                    "Seed data namespace 'seed' conflicts with existing action. "
                    "Seed data will overwrite it."
                )
            prompt_context["seed"] = static_data
            logger.debug("[SEED_DATA] Added to prompt_context under 'seed' namespace")

        # Process DROP: Remove from prompt_context (security)
        drop_refs = context_scope.get("drop", [])
        for field_ref in drop_refs:
            try:
                ns_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Remove from prompt_context
                if ns_name in prompt_context and isinstance(prompt_context[ns_name], dict):
                    prompt_context[ns_name].pop(field_name, None)

            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="drop",
                    )
                )
                continue

        # Process OBSERVE: Extract to llm_context, KEEP in prompt_context for template rendering
        observe_refs = context_scope.get("observe", [])
        for field_ref in observe_refs:
            try:
                ns_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                if field_name == "*":
                    action_fields = ContextScopeProcessor.extract_action_fields(
                        field_context, ns_name
                    )
                    if action_fields:
                        llm_context.update(action_fields)
                else:
                    # Extract value from original field_context (before drop removed it)
                    value = ContextScopeProcessor.extract_field_value(
                        field_context, ns_name, field_name
                    )

                    if value is not None:
                        # Add to llm_context (flat dict with field names as keys)
                        llm_context[field_name] = value

                    # DO NOT remove from prompt_context - users need it for {{action.field}} template refs

            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="observe",
                    )
                )
                continue

        # Process PASSTHROUGH: Extract to passthrough_fields, remove from prompt_context
        passthrough_refs = context_scope.get("passthrough", [])
        for field_ref in passthrough_refs:
            try:
                ns_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                if field_name == "*":
                    action_fields = ContextScopeProcessor.extract_action_fields(
                        field_context, ns_name
                    )
                    if action_fields:
                        passthrough_fields.update(action_fields)
                else:
                    # Extract value from original field_context
                    value = ContextScopeProcessor.extract_field_value(
                        field_context, ns_name, field_name
                    )

                    if value is not None:
                        # Add to passthrough_fields (flat dict with field names as keys)
                        passthrough_fields[field_name] = value

            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="passthrough",
                    )
                )
                continue

        # Fire event for scope application
        fire_event(
            ContextScopeAppliedEvent(
                action_name=action_name,
                observe_count=len(observe_refs),
                passthrough_count=len(passthrough_refs),
                drop_count=len(drop_refs),
                observe_fields=observe_refs,
                passthrough_fields=passthrough_refs,
                drop_fields=drop_refs,
            )
        )

        return (prompt_context, llm_context, passthrough_fields)

    @staticmethod
    def format_llm_context(llm_context: Dict) -> str:
        """Format llm_context dict as readable text for LLM message injection."""
        if not llm_context:
            return ""

        lines = ["Additional context:"]

        for key, value in llm_context.items():
            # Format value as pretty JSON for readability
            value_str = json.dumps(value, indent=2, ensure_ascii=False)
            lines.append(f"{key}: {value_str}")

        return "\n".join(lines)

    @staticmethod
    def merge_passthrough_fields(llm_response: List[Dict], passthrough_fields: Dict) -> List[Dict]:
        """Merge passthrough fields into LLM response."""
        if not passthrough_fields:
            # No passthrough fields to merge
            return llm_response

        # Handle list of items
        if isinstance(llm_response, list):
            for item in llm_response:
                if isinstance(item, dict):
                    # Check if structured format with 'content' key
                    if "content" in item and isinstance(item["content"], dict):
                        # Merge into content
                        item["content"].update(passthrough_fields)
                    else:
                        # Merge directly into item
                        item.update(passthrough_fields)
            return llm_response

        # Handle single dict
        if isinstance(llm_response, dict):
            # Check if structured format with 'content' key
            if "content" in llm_response and isinstance(llm_response["content"], dict):
                # Merge into content
                llm_response["content"].update(passthrough_fields)
            else:
                # Merge directly
                llm_response.update(passthrough_fields)
            return llm_response

        # Other types (shouldn't happen, but be defensive)
        return llm_response

    @staticmethod
    def _extract_content_data(source_content: Any) -> Dict:
        """
        Extract content portion from record structure.

        Handles both:
        - {source_guid, content: {...}} wrapper → extract content
        - Flat dict → return as-is (excluding metadata keys)
        """
        if not isinstance(source_content, dict):
            return {}

        # Wrapped format: {source_guid, content: {...}}
        if "content" in source_content and isinstance(source_content["content"], dict):
            return source_content["content"]

        # Flat format: {...} but exclude metadata keys
        return {
            k: v
            for k, v in source_content.items()
            if k
            not in [
                "source_guid",
                "lineage",
                "node_id",
                "metadata",
                "target_id",
                "parent_target_id",
                "root_target_id",
                "chunk_info",
                # System fields: excluded so they don't leak into downstream prompts
                "_recovery",  # batch retry recovery metadata
                "_unprocessed",  # circuit-breaker flag for upstream failures
            ]
        }

    @staticmethod
    def _enrich_source_namespace(
        base_namespace: Dict[str, Any], current_item: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge fallback fields into the source namespace from the current item.

        This helps downstream actions get at least one source-like namespace even if the
        stored source file was sparse (e.g., only identifiers).
        """
        merged = dict(base_namespace or {})

        if not current_item or not isinstance(current_item, dict):
            return merged

        fallback = ContextScopeProcessor._extract_content_data(current_item)
        for key, value in fallback.items():
            if key not in merged:
                merged[key] = value

        return merged

    @staticmethod
    def _load_historical_node(
        action_name: str,
        lineage: List[str],
        source_guid: str,
        file_path: str,
        agent_indices: Dict[str, int],
        parent_target_id: Optional[str] = None,
        root_target_id: Optional[str] = None,
        output_directory: Optional[str] = None,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> Optional[Dict]:
        """
        Load historical node data from saved files or storage backend.

        Uses HistoricalNodeDataLoader with HistoricalDataRequest.
        Returns content dict or None if not found.

        Args:
            action_name: Name of the action to load historical data for
            lineage: Lineage chain of the current record
            source_guid: Source GUID to match
            file_path: Path to the current file being processed
            agent_indices: Mapping of action names to their indices
            parent_target_id: Optional parent target ID for ancestry matching
            root_target_id: Optional root target ID for Map-Reduce matching
            output_directory: Optional output directory (legacy, unused)
            storage_backend: Optional storage backend for SQLite/TinyDB queries
        """
        from agent_actions.input.context.historical import (
            HistoricalNodeDataLoader,
            HistoricalDataRequest,
        )

        request = HistoricalDataRequest(
            action_name=action_name,
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices,
            caller_lineage=lineage,
            parent_target_id=parent_target_id,
            root_target_id=root_target_id,
            output_directory=output_directory,
            storage_backend=storage_backend,
        )

        return HistoricalNodeDataLoader.load_historical_node_data(request)

    @staticmethod
    def _detect_version_namespaces(
        input_data: Dict[str, Any], input_sources: List[str]
    ) -> List[str]:
        """
        Detect if input_data contains nested version namespaces from version_consumption merge.

        Version namespaces are created when upstream actions use version_consumption with merge pattern.
        They have the pattern: action_name_N where N is a digit.

        Args:
            input_data: Content data that may contain nested version namespaces
            input_sources: List of input source names to check against

        Returns:
            List of detected version namespace names (e.g., ["action_1", "action_2", "action_3"])

        Example:
            input_data = {
                "generate_answer_1": {"answer": "..."},
                "generate_answer_2": {"answer": "..."},
                "some_field": "value"
            }
            input_sources = ["generate_answer_1", "generate_answer_2"]

            Returns: ["generate_answer_1", "generate_answer_2"]
        """
        if not input_data or not isinstance(input_data, dict):
            return []

        version_namespaces = []

        # Check if any keys in input_data match version iteration pattern
        for key in input_data.keys():
            # Check if this key looks like a version iteration: ends with _N where N is digit
            if "_" in key:
                parts = key.rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    # Check if this matches any input source or is a variant of an input source
                    if key in input_sources:
                        # Direct match - this is a version namespace
                        version_namespaces.append(key)
                        logger.debug(
                            f"[VERSION DETECT] '{key}' matches input source - treating as version namespace"
                        )
                    else:
                        # Check if the base name (without _N) is referenced in input sources
                        base_name = parts[0]
                        # Check if any input source is a version of this base
                        has_version_siblings = any(
                            src.startswith(f"{base_name}_") and src.rsplit("_", 1)[1].isdigit()
                            for src in input_sources
                        )
                        if has_version_siblings:
                            version_namespaces.append(key)
                            logger.debug(
                                f"[VERSION DETECT] '{key}' has version siblings in input_sources - "
                                f"treating as version namespace"
                            )

        return version_namespaces

    @staticmethod
    def _filter_and_store_fields(
        field_context: Dict,
        name: str,
        data: Dict,
        allowed_fields: Optional[List[str]],
        source_type: str = "FIELD",
        warn_missing: bool = False,
        metadata_collector: Optional[Dict] = None,
    ) -> None:
        """
        Filter data by allowed_fields and store in field_context.

        Args:
            field_context: Target dict to store filtered data
            name: Key name for storing in field_context
            data: Source data to filter
            allowed_fields: Fields to include (None = wildcard, all fields)
            source_type: Log prefix for debug messages (e.g., "INPUT SOURCE")
            warn_missing: If True, log warning for missing fields
            metadata_collector: Optional dict to record stored vs loaded field metadata.
                When provided, records {name: {stored_fields, loaded_fields, stored_count, loaded_count}}
                for downstream diagnostics (e.g. detecting fields produced by tools but not in schema).
        """
        stored_fields = set(data.keys())

        if allowed_fields is None:
            # Wildcard: Load all fields
            field_context[name] = data
            logger.debug(
                "[%s] Loaded '%s' with ALL %d fields (wildcard)",
                source_type,
                name,
                len(data),
            )
            if metadata_collector is not None:
                metadata_collector[name] = {
                    "stored_fields": sorted(stored_fields),
                    "loaded_fields": sorted(stored_fields),
                    "stored_count": len(stored_fields),
                    "loaded_count": len(stored_fields),
                }
        else:
            # Specific fields: Filter
            filtered_data = {}
            for field in allowed_fields:
                if field in data:
                    # Exact key match (flat field or literal dotted key)
                    filtered_data[field] = data[field]
                elif "." in field:
                    # Nested path: extract only the declared subfield
                    if nested_field_exists(data, field):
                        set_nested_value(filtered_data, field, get_nested_value(data, field))
            if warn_missing:
                missing_fields = set()
                for field in allowed_fields:
                    if field in data:
                        continue
                    if "." in field and field.split(".")[0] in data:
                        continue
                    missing_fields.add(field)
                if missing_fields:
                    logger.warning(
                        "[%s] '%s': fields %s not found. Available: %s",
                        source_type,
                        name,
                        missing_fields,
                        list(data.keys()),
                    )
            field_context[name] = filtered_data
            logger.debug(
                "[%s] Loaded '%s' with %d fields: %s",
                source_type,
                name,
                len(filtered_data),
                list(filtered_data.keys()),
            )
            if metadata_collector is not None:
                loaded_fields = sorted(filtered_data.keys())
                metadata_collector[name] = {
                    "stored_fields": sorted(stored_fields),
                    "loaded_fields": loaded_fields,
                    "stored_count": len(stored_fields),
                    "loaded_count": len(loaded_fields),
                }

    @staticmethod
    def _extract_allowed_fields_per_dependency(
        dependencies: List[str], context_scope: Optional[Dict], action_name: str = "unknown"
    ) -> Dict[str, Optional[List[str]]]:
        """
        Extract which fields are allowed for each dependency from context_scope.

        Returns dict mapping dependency name to:
        - None: Wildcard (all fields allowed)
        - List[str]: Specific field names allowed
        - Empty list: No fields declared (shouldn't happen, but defensive)

        Example:
            context_scope = {
                "observe": ["add_answer_text.*", "classify.question_type"],
                "passthrough": ["add_answer_text.question"]
            }
            dependencies = ["add_answer_text", "classify"]

            Returns:
            {
                "add_answer_text": None,  # Wildcard
                "classify": ["question_type"]  # Specific field
            }
        """
        if not context_scope:
            if dependencies:
                logger.error(
                    f"Action '{action_name}' has dependencies but no context_scope defined."
                )
                raise ConfigurationError(
                    f"Action '{action_name}' has dependencies but no context_scope defined. "
                    f"All dependencies must have explicit field declarations.\n\n"
                    f"Dependencies: {dependencies}",
                    context={"action": action_name, "dependencies": dependencies},
                )
            return {}

        allowed_per_dep: Dict[str, Optional[List[str]]] = {}

        # Collect field references from observe and passthrough
        # (both need to be loaded into field_context)
        all_field_refs = []
        all_field_refs.extend(context_scope.get("observe", []))
        all_field_refs.extend(context_scope.get("passthrough", []))

        # Track which dependencies are declared in context_scope
        # Also track field prefix patterns (for loop consumption)
        declared_deps = set()
        field_prefix_patterns = (
            set()
        )  # Base names with field prefix patterns (e.g., 'extract_raw_qa')

        for field_ref in all_field_refs:
            try:
                ref_action, ref_field = ContextScopeProcessor.parse_field_reference(field_ref)
                declared_deps.add(ref_action)
                # Track field prefix patterns (indicated by '_' field marker)
                if ref_field == "_":
                    field_prefix_patterns.add(ref_action)
            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=field_ref,
                        reason=str(e),
                        directive="extract_allowed_fields",
                    )
                )
                continue

        for dep_name in dependencies:
            wildcard_found = False
            specific_fields = []

            for field_ref in all_field_refs:
                try:
                    ref_action, ref_field = ContextScopeProcessor.parse_field_reference(field_ref)

                    # Check for exact match or field prefix pattern match
                    if ref_action != dep_name:
                        # Check if this is a field prefix pattern that covers the dependency
                        if ref_field == "_" and dep_name.startswith(f"{ref_action}_"):
                            # Field prefix pattern covers all loop iterations
                            wildcard_found = True
                            break
                        continue  # Not for this dependency

                    if ref_field == "*":
                        # Wildcard: dep_name.*
                        wildcard_found = True
                        break
                    elif ref_field == "_":
                        # Field prefix pattern: dep_name_
                        wildcard_found = True
                        break
                    else:
                        # Specific field: dep_name.field_name
                        specific_fields.append(ref_field)

                except ValueError as e:
                    fire_event(
                        ContextFieldSkippedEvent(
                            action_name=action_name,
                            field_ref=field_ref,
                            reason=str(e),
                            directive="extract_allowed_fields_inner",
                        )
                    )
                    continue

            if wildcard_found:
                allowed_per_dep[dep_name] = None  # All fields
            elif specific_fields:
                allowed_per_dep[dep_name] = list(set(specific_fields))  # Deduplicate
            else:
                # Dependency declared but no fields referenced in context_scope
                # This is now an error (no implicit field loading)
                logger.error(
                    f"Dependency '{dep_name}' declared but not referenced in context_scope. "
                    f"All dependencies must have explicit field declarations."
                )
                raise ConfigurationError(
                    f"Dependency '{dep_name}' declared but not referenced in context_scope. "
                    f"Add field declarations (e.g., '{dep_name}.*' or '{dep_name}.field_name').\n\n"
                    f"All dependencies: {dependencies}\n"
                    f"Declared in context_scope: {list(declared_deps)}",
                    context={
                        "action": action_name,
                        "missing_dependency": dep_name,
                        "all_dependencies": dependencies,
                        "declared_dependencies": list(declared_deps),
                    },
                )

        return allowed_per_dep

    @staticmethod
    # Complex field context building with historical data requires all these parameters
    def build_field_context_with_history(
        contents: Dict,  # Legacy parameter, not used
        agent_name: str,
        agent_config: Optional[Dict],
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,  # Legacy, not used
        source_content: Optional[Any] = None,
        version_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        context_scope: Optional[Dict] = None,
        output_directory: Optional[str] = None,
        storage_backend: Optional["StorageBackend"] = None,
        metadata_collector: Optional[Dict] = None,
    ) -> Dict:
        """
        Build field context with explicit namespace structure.

        AUTO-INFERRED CONTEXT DEPENDENCIES:
        - Input sources (from dependencies field): Data already in current_item
        - Context sources (auto-inferred from context_scope): Loaded via historical loader

        IMPORTANT: agent_indices is REQUIRED when action has dependencies.
        No fallbacks - this ensures consistent behavior across all execution modes.

        Architecture (per anatomy_action.md):
        field_context = {
            "source": {...},        # Original input data
            "{dep_name}": {...},    # Dependency action outputs (FILTERED by context_scope)
            "seed": {...},          # Static reference data (via static_data)
            "version": {...},       # Version iteration info (i, idx, length, first, last)
            "workflow": {...},      # Workflow metadata
        }

        Args:
            contents: Legacy parameter (not used)
            agent_name: Name of the current action
            agent_config: Action configuration dict
            agent_indices: REQUIRED if action has dependencies. Maps action names to positions.
            dependency_configs: Legacy parameter (not used)
            source_content: Original input data for "source" namespace
            version_context: Loop iteration info
            workflow_metadata: Workflow metadata
            current_item: Current record being processed (has lineage, content)
            file_path: Path to current file
            context_scope: Controls which fields to load (progressive data exposure)
            output_directory: Optional output directory (legacy, unused)
            storage_backend: Optional storage backend for loading historical data from SQLite/TinyDB

        Returns:
            Dict with namespaces: source, {dep_names}, version, workflow

        Raises:
            ConfigurationError: If action has dependencies but agent_indices not provided

        Progressive Data Exposure:
        - context_scope.observe: ["dep.field1", "dep.*"] -> Controls what gets loaded
        - context_scope.passthrough: ["dep.field2"] -> Also loaded (needed for output)
        - Undeclared fields never enter memory
        """
        from agent_actions.input.context.historical import (
            HistoricalNodeDataLoader,
        )

        field_context = {}

        # 1. SOURCE namespace - original input data
        source_namespace = {}
        if source_content:
            source_namespace = ContextScopeProcessor._extract_content_data(source_content)

        source_namespace = ContextScopeProcessor._enrich_source_namespace(
            source_namespace, current_item
        )

        if source_namespace:
            field_context["source"] = source_namespace
            logger.debug("Added 'source' namespace with %s fields", len(field_context["source"]))
            fire_event(
                ContextNamespaceLoadedEvent(
                    action_name=agent_name,
                    namespace="source",
                    field_count=len(source_namespace),
                    fields=list(source_namespace.keys()),
                )
            )

        # 2. DEPENDENCY namespaces - separate input sources from context sources
        logger.debug(
            "[CONTEXT BUILD] Action '%s': agent_config=%s, agent_indices=%s, current_item=%s, file_path=%s",
            agent_name,
            bool(agent_config),
            len(agent_indices) if agent_indices else 0,
            bool(current_item),
            bool(file_path),
        )
        batch_mode_enabled = bool(agent_config and agent_indices and current_item and file_path)
        logger.debug(
            "[CONTEXT BUILD] Action '%s': batch_mode_enabled=%s (config=%s, indices=%s, item=%s, path=%s)",
            agent_name,
            batch_mode_enabled,
            bool(agent_config),
            bool(agent_indices),
            bool(current_item),
            bool(file_path),
        )
        if batch_mode_enabled:
            # BATCH MODE - Use auto-inferred context dependencies
            workflow_actions = list(agent_indices.keys())

            # Infer input sources vs context sources
            input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
                agent_config, workflow_actions, agent_name
            )

            logger.debug(
                "[AUTO-INFER] Action '%s': input_sources=%s, context_sources=%s",
                agent_name,
                input_sources,
                context_sources,
            )

            lineage = current_item.get("lineage", [])
            source_guid = current_item.get("source_guid")
            current_idx = agent_indices.get(agent_name, 999)

            # 2a. INPUT SOURCES - Data is already in current_item (the file being processed)
            # Put it under the action name so prompts can reference {{ action_name.field }}
            if input_sources and current_item:
                input_data = ContextScopeProcessor._extract_content_data(current_item)

                # Get allowed fields for input sources
                all_deps_for_fields = input_sources + context_sources
                allowed_fields_map = ContextScopeProcessor._extract_allowed_fields_per_dependency(
                    all_deps_for_fields, context_scope, agent_name
                )

                # Check if input_data contains nested version namespaces from version_consumption
                # This happens when upstream action used version_consumption with merge pattern
                # Structure: {version_1: {fields}, version_2: {fields}, ...}
                version_namespaces_detected = ContextScopeProcessor._detect_version_namespaces(
                    input_data, input_sources
                )

                if version_namespaces_detected:
                    # Split nested version namespaces into separate top-level namespaces
                    logger.debug(
                        f"[VERSION NAMESPACES] Detected nested version namespaces in input_data: "
                        f"{version_namespaces_detected}"
                    )

                    for version_name, version_data in input_data.items():
                        if not isinstance(version_data, dict):
                            # Not a version namespace, skip
                            continue

                        if version_name not in version_namespaces_detected:
                            # Not a detected version namespace, skip
                            continue

                        # Add as separate namespace in field_context
                        allowed_fields = allowed_fields_map.get(version_name)
                        ContextScopeProcessor._filter_and_store_fields(
                            field_context,
                            version_name,
                            version_data,
                            allowed_fields,
                            source_type="VERSION NAMESPACE",
                            metadata_collector=metadata_collector,
                        )

                    # Load parallel version sources via historical lookup
                    # When input_sources has multiple versioned branches (e.g., action_1, action_2),
                    # current_item only contains data from one. Load others from historical data.
                    parallel_version_sources = [
                        src
                        for src in input_sources
                        if src not in field_context and src in agent_indices
                    ]
                    if parallel_version_sources and source_guid:
                        logger.debug(
                            f"[PARALLEL VERSIONS] Loading {len(parallel_version_sources)} parallel "
                            f"version sources via historical lookup: {parallel_version_sources}"
                        )
                        for version_source in parallel_version_sources:
                            version_idx = agent_indices.get(version_source)
                            if version_idx is None or version_idx >= current_idx:
                                continue

                            historical_data = ContextScopeProcessor._load_historical_node(
                                action_name=version_source,
                                lineage=lineage,
                                source_guid=source_guid,
                                file_path=file_path,
                                agent_indices=agent_indices,
                                parent_target_id=current_item.get("parent_target_id"),
                                root_target_id=current_item.get("root_target_id"),
                                output_directory=output_directory,
                                storage_backend=storage_backend,
                            )

                            if historical_data:
                                allowed_fields = allowed_fields_map.get(version_source)
                                ContextScopeProcessor._filter_and_store_fields(
                                    field_context,
                                    version_source,
                                    historical_data,
                                    allowed_fields,
                                    source_type="PARALLEL VERSION",
                                    metadata_collector=metadata_collector,
                                )
                            else:
                                logger.warning(
                                    f"[PARALLEL VERSION] Could not load '{version_source}' "
                                    f"via historical lookup. source_guid={source_guid}"
                                )
                else:
                    # No version namespaces detected - use original behavior
                    logger.debug(
                        f"[INPUT SOURCE] input_data keys: {list(input_data.keys()) if input_data else 'EMPTY'}"
                    )
                    for input_source_name in input_sources:
                        allowed_fields = allowed_fields_map.get(input_source_name)
                        logger.debug(
                            "[INPUT SOURCE] '%s': allowed_fields=%s",
                            input_source_name,
                            allowed_fields,
                        )
                        ContextScopeProcessor._filter_and_store_fields(
                            field_context,
                            input_source_name,
                            input_data,
                            allowed_fields,
                            source_type="INPUT SOURCE",
                            warn_missing=True,
                            metadata_collector=metadata_collector,
                        )

            # 2b. CONTEXT SOURCES - Load via historical loader (lineage matching)
            logger.debug(
                "[CONTEXT SOURCES CHECK] Action '%s': context_sources=%s, will load=%s",
                agent_name,
                context_sources,
                bool(context_sources),
            )
            if context_sources:
                # Get allowed fields for context sources
                if "allowed_fields_map" not in locals():
                    all_deps_for_fields = input_sources + context_sources
                    allowed_fields_map = (
                        ContextScopeProcessor._extract_allowed_fields_per_dependency(
                            all_deps_for_fields, context_scope, agent_name
                        )
                    )

                logger.debug(
                    "[CONTEXT SOURCES] Loading %d context dependencies: %s (storage_backend=%s)",
                    len(context_sources),
                    context_sources,
                    "available" if storage_backend else "NOT available",
                )

                for dep_name in context_sources:
                    # Skip special reserved namespaces - they're populated differently
                    if dep_name in SPECIAL_NAMESPACES:
                        logger.debug(
                            "Skipping special namespace '%s' (handled separately)", dep_name
                        )
                        continue

                    # Check if dependency should be loaded
                    dep_idx = agent_indices.get(dep_name)
                    if dep_idx is None:
                        logger.warning(
                            f"Context dependency '{dep_name}' not found in agent_indices. "
                            f"Available: {list(agent_indices.keys())}"
                        )
                        continue

                    if dep_idx >= current_idx:
                        logger.debug(
                            f"Skipping context dependency '{dep_name}' (comes after current action)"
                        )
                        continue

                    # Parallel Branch Check
                    is_ancestor = (
                        HistoricalNodeDataLoader._find_node_in_lineage(
                            dep_name, lineage, agent_indices
                        )
                        is not None
                    )

                    if not is_ancestor:
                        logger.debug(
                            f"Context dependency '{dep_name}' not in lineage (may not have executed yet). "
                            f"Will attempt to load from historical files."
                        )

                    # Load historical data
                    logger.debug(
                        f"[HISTORICAL LOAD] Loading context dep '{dep_name}' from file_path={file_path}"
                    )
                    historical_data = ContextScopeProcessor._load_historical_node(
                        action_name=dep_name,
                        lineage=lineage,
                        source_guid=source_guid,
                        file_path=file_path,
                        agent_indices=agent_indices,
                        parent_target_id=current_item.get("parent_target_id"),
                        root_target_id=current_item.get("root_target_id"),
                        output_directory=output_directory,
                        storage_backend=storage_backend,
                    )

                    logger.debug(
                        "[HISTORICAL] Action '%s': dep='%s' -> %s",
                        agent_name,
                        dep_name,
                        "FOUND" if historical_data else "NOT FOUND",
                    )
                    if historical_data is None:
                        logger.warning(
                            f"[CONTEXT SOURCE] Context dependency '{dep_name}' historical data not found. "
                            f"Lineage: {lineage}, source_guid: {source_guid}. "
                            f"Dependency will not be available in field_context."
                        )
                        continue

                    logger.debug(
                        "[HISTORICAL LOAD] Loaded context dep '%s': fields=%s",
                        dep_name,
                        list(historical_data.keys()),
                    )

                    # PROGRESSIVE DATA EXPOSURE: Filter to only allowed fields
                    allowed_fields = allowed_fields_map.get(dep_name)
                    ContextScopeProcessor._filter_and_store_fields(
                        field_context,
                        dep_name,
                        historical_data,
                        allowed_fields,
                        source_type="CONTEXT SOURCE",
                        warn_missing=True,
                        metadata_collector=metadata_collector,
                    )

        else:
            # Log why batch mode condition wasn't met
            logger.debug(
                "[CONTEXT BUILD SKIP] Action '%s': Batch mode condition not met. "
                "agent_config=%s, agent_indices=%s, current_item=%s, file_path=%s",
                agent_name,
                bool(agent_config),
                len(agent_indices) if agent_indices else 0,
                bool(current_item),
                bool(file_path),
            )

        if agent_config and agent_config.get("dependencies") and not agent_indices:
            # ERROR: Dependencies declared but no agent_indices provided
            # agent_indices is REQUIRED for dependency resolution (no fallbacks)
            dependencies = agent_config.get("dependencies", [])
            raise ConfigurationError(
                f"Action '{agent_name}' has dependencies {dependencies} but agent_indices was not provided. "
                f"agent_indices is required for dependency resolution.\n\n"
                f"Ensure the workflow orchestrator passes agent_indices to build_field_context_with_history().",
                context={
                    "action": agent_name,
                    "dependencies": dependencies,
                    "hint": "agent_indices must be a dict mapping action names to their positions",
                },
            )

        # 3. VERSION namespace - iteration info (for version actions)
        # Provides {{ version.length }}, {{ version.first }}, {{ version.last }}
        # Also adds top-level {{ i }}, {{ idx }}, and custom param names
        if version_context:
            field_context["version"] = version_context
            # Add common version variables at top level for convenience
            # This enables {{ i }} instead of requiring {{ version.i }}
            if "i" in version_context:
                field_context["i"] = version_context["i"]
            if "idx" in version_context:
                field_context["idx"] = version_context["idx"]
            # Add custom param names at top level (e.g., {{ classifier_id }})
            reserved_keys = {"i", "idx", "length", "first", "last"}
            for key, value in version_context.items():
                if key not in reserved_keys:
                    field_context[key] = value
            logger.debug("Added 'version' namespace with version context")
            fire_event(
                ContextNamespaceLoadedEvent(
                    action_name=agent_name,
                    namespace="version",
                    field_count=len(version_context),
                    fields=list(version_context.keys()),
                )
            )

        # 4. WORKFLOW namespace - metadata
        if workflow_metadata:
            field_context["workflow"] = workflow_metadata
            logger.debug("Added 'workflow' namespace")
            fire_event(
                ContextNamespaceLoadedEvent(
                    action_name=agent_name,
                    namespace="workflow",
                    field_count=len(workflow_metadata),
                    fields=list(workflow_metadata.keys()),
                )
            )

        logger.debug(
            f"Built field_context for '{agent_name}' with namespaces: {list(field_context.keys())}"
        )

        # DEBUG: Show what's in each namespace
        for ns in field_context.keys():
            if isinstance(field_context[ns], dict):
                logger.debug(
                    f"DEBUG: field_context['{ns}'] has fields: {list(field_context[ns].keys())}"
                )

        return field_context

    # ------------------------------------------------------------------
    # File-mode observe filtering (replaces pipeline._apply_observe_filter)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_observe_refs(
        observe_refs: List[str],
        action_name: str = "unknown",
    ) -> List[Tuple[str, str, str]]:
        """Parse observe refs and detect bare-key collisions.

        Returns list of ``(namespace, field_name, output_key)`` triples.

        * *namespace* – the action/source prefix (left of the dot).
        * *field_name* – the bare field name (right of the dot), ``*`` or ``_``.
        * *output_key* – the key to use in the filtered output dict.  Bare by
          default; qualified (``namespace.field``) when collisions are detected.
        """
        parsed: List[Tuple[str, str, str]] = []  # will be re-keyed below
        valid_pairs: List[Tuple[str, str]] = []  # (namespace, field_name)

        for ref in observe_refs:
            try:
                ns, field = ContextScopeProcessor.parse_field_reference(ref)
                valid_pairs.append((ns, field))
            except ValueError as e:
                fire_event(
                    ContextFieldSkippedEvent(
                        action_name=action_name,
                        field_ref=ref,
                        reason=str(e),
                        directive="resolve_observe_refs",
                    )
                )
                continue

        # Detect bare-key collisions across all namespaces.
        bare_counts = Counter(field for _, field in valid_pairs)
        collisions = {k for k, v in bare_counts.items() if v > 1}

        for ns, field in valid_pairs:
            output_key = f"{ns}.{field}" if field in collisions else field
            parsed.append((ns, field, output_key))

        return parsed

    @staticmethod
    def _load_file_mode_cross_namespace_data(
        needed_ns: set,
        record: Dict,
        agent_name: str,
        agent_indices: Optional[Dict[str, int]] = None,
        file_path: Optional[str] = None,
        source_record: Optional[Dict] = None,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> Dict[str, Dict]:
        """Load data for namespaces NOT present in the per-record content.

        Returns ``{namespace: {field: value}}`` for source and context-dep
        namespaces.  Input-source namespaces (whose data lives in each record's
        ``content``) are *not* loaded here.

        *needed_ns* is the set of namespace identifiers that require
        cross-namespace loading, pre-computed by the caller (which applies
        the ``has_reliable_ns`` gate).  This method must not recompute it.

        Called once per unique ancestry key in a file; the caller caches the
        result so that records sharing the same key skip redundant I/O.
        """
        cross_ns: Dict[str, Dict] = {}

        # Defensive copy — we mutate via discard below.
        needed_ns = set(needed_ns)

        if not needed_ns:
            return cross_ns

        # --- "source" namespace: use the matched source record ----
        if "source" in needed_ns:
            needed_ns.discard("source")
            if source_record:
                cross_ns["source"] = ContextScopeProcessor._extract_content_data(source_record)
            else:
                logger.warning(
                    "[FILE OBSERVE] 'source' namespace referenced but no source_record available "
                    "for action '%s'.",
                    agent_name,
                )

        # --- context dependency namespaces: load via historical lookup -----
        if needed_ns and record and agent_indices and file_path:
            lineage = record.get("lineage", [])
            source_guid = record.get("source_guid")
            current_idx = agent_indices.get(agent_name, 999)

            for ns in needed_ns:
                dep_idx = agent_indices.get(ns)
                if dep_idx is None:
                    logger.warning(
                        "[FILE OBSERVE] Namespace '%s' not found in agent_indices for action '%s'. "
                        "Available: %s. Skipping.",
                        ns,
                        agent_name,
                        list(agent_indices.keys()),
                    )
                    continue
                if dep_idx >= current_idx:
                    logger.debug(
                        "[FILE OBSERVE] Skipping namespace '%s' (comes after current action '%s').",
                        ns,
                        agent_name,
                    )
                    continue

                if not source_guid:
                    logger.warning(
                        "[FILE OBSERVE] Cannot load namespace '%s': record has no "
                        "source_guid. action='%s'.",
                        ns,
                        agent_name,
                    )
                    continue

                try:
                    hist = ContextScopeProcessor._load_historical_node(
                        action_name=ns,
                        lineage=lineage,
                        source_guid=source_guid,
                        file_path=file_path,
                        agent_indices=agent_indices,
                        parent_target_id=record.get("parent_target_id"),
                        root_target_id=record.get("root_target_id"),
                        storage_backend=storage_backend,
                    )
                    if hist:
                        cross_ns[ns] = hist
                    else:
                        logger.warning(
                            "[FILE OBSERVE] Historical data not found for namespace '%s'. "
                            "action='%s', source_guid=%s.",
                            ns,
                            agent_name,
                            source_guid,
                        )
                except Exception:
                    logger.warning(
                        "[FILE OBSERVE] Failed to load historical data for namespace '%s'. "
                        "action='%s'. Skipping.",
                        ns,
                        agent_name,
                        exc_info=True,
                    )
        elif needed_ns:
            for ns in needed_ns:
                logger.warning(
                    "[FILE OBSERVE] Cannot load namespace '%s': missing agent_indices/file_path/record "
                    "for action '%s'. Skipping.",
                    ns,
                    agent_name,
                )

        return cross_ns

    @staticmethod
    def apply_observe_for_file_mode(
        data: List[Dict],
        agent_config: Dict,
        agent_name: str,
        agent_indices: Optional[Dict[str, int]] = None,
        file_path: Optional[str] = None,
        source_data: Optional[List[Dict]] = None,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> List[Dict]:
        """Namespace-aware observe filter for file-mode (array-level) data.

        Replaces the simplified ``_apply_observe_filter`` which stripped
        namespaces and looked up bare keys in the record content.  This method
        resolves cross-namespace references (``source.url``, context deps)
        correctly.

        Returns a filtered ``List[Dict]`` with the same shape as the old method
        so downstream callers (``_process_file_mode_tool``,
        ``_process_file_mode_hitl``) are unaffected.
        """
        context_scope = agent_config.get("context_scope") or {}
        observe_refs = context_scope.get("observe")
        if not observe_refs:
            return data

        resolved = ContextScopeProcessor._resolve_observe_refs(observe_refs, action_name=agent_name)
        if not resolved:
            return data

        # Wildcard ("*") or prefix-passthrough ("_") pattern → return all data
        # unfiltered.  "_" is the sentinel produced by _resolve_observe_refs for
        # the "namespace._" syntax which passes through all fields whose keys
        # start with the namespace prefix.
        if any(field in ("*", "_") for _, field, _ in resolved):
            return data

        # Determine which namespaces are "input sources" (data in each record).
        # Use fan-in-aware inference so non-primary deps are loaded historically.
        # `has_reliable_ns` tracks whether input_source_names contains real
        # namespace identifiers (from deps/infer_dependencies) vs content-key
        # guesses.  When True, we can safely gate content fallback to only
        # input-source namespaces; when False we must allow it for all refs.
        input_source_names: set = set()
        has_reliable_ns = False
        if agent_indices:
            try:
                input_sources, _ = ContextScopeProcessor.infer_dependencies(
                    agent_config, list(agent_indices.keys()), agent_name
                )
                input_source_names = set(input_sources)
                has_reliable_ns = bool(input_source_names)
            except Exception:
                logger.debug(
                    "[FILE OBSERVE] infer_dependencies failed for '%s'; "
                    "falling back to raw dependencies.",
                    agent_name,
                    exc_info=True,
                )

        if not input_source_names:
            # Fallback: raw dependencies or content-key heuristic.
            deps = (
                agent_config["dependencies"]
                if "dependencies" in agent_config
                else agent_config.get("depends_on")
            )
            if deps:
                if isinstance(deps, str):
                    input_source_names = {deps}
                else:
                    input_source_names = set(deps)
                has_reliable_ns = True
            elif data and isinstance(data[0], dict):
                # Best-effort heuristic: treat all top-level keys in record
                # content as input-source namespaces.  This can misclassify a
                # key that coincidentally matches a namespace name, but without
                # explicit dependencies there is no reliable way to distinguish
                # input-source keys from metadata.  has_reliable_ns stays False.
                sample = data[0]
                sample_content = (
                    sample.get("content", sample)
                    if isinstance(sample.get("content"), dict)
                    else sample
                )
                input_source_names = set(sample_content.keys())

        # Determine which namespaces need cross-namespace loading.
        # "source" is always a known cross-namespace ref (loaded from
        # source_data, not historical lookups) so it is always eligible.
        # Other namespaces require has_reliable_ns because when
        # input_source_names contains content keys (heuristic), the
        # `ns not in input_source_names` check would misclassify every
        # namespace as cross-namespace and trigger spurious historical
        # loads whose stale results would shadow live record data.
        needed_ns: set = set()
        for ns, field, _ in resolved:
            if field in ("*", "_"):
                continue
            if ns == "source":
                needed_ns.add(ns)
            elif has_reliable_ns and ns not in input_source_names:
                needed_ns.add(ns)

        # Build source index for matching source records by source_guid.
        source_index: Dict[Optional[str], Dict] = {}
        if "source" in needed_ns and source_data:
            for src in source_data:
                sguid = src.get("source_guid") if isinstance(src, dict) else None
                if sguid:
                    source_index[sguid] = src

        # Per-record loop with ancestry-aware cache.
        # Historical lookups depend on source_guid + lineage + parent/root target IDs,
        # so the cache key must include all discriminators to avoid returning stale
        # data when records share a source_guid but diverge in ancestry.
        cross_ns_cache: Dict[tuple, Dict[str, Dict]] = {}
        filtered: List[Dict] = []
        for item in data:
            if not isinstance(item, dict):
                filtered.append(item)
                continue

            content = item.get("content", item) if isinstance(item.get("content"), dict) else item

            # Resolve cross-namespace data (cached by ancestry key).
            if needed_ns:
                sguid = item.get("source_guid")
                cache_key = (
                    sguid,
                    tuple(item.get("lineage", [])),
                    item.get("parent_target_id"),
                    item.get("root_target_id"),
                )
                if cache_key not in cross_ns_cache:
                    matched_source = source_index.get(
                        sguid, source_data[0] if source_data else None
                    )
                    cross_ns_cache[cache_key] = (
                        ContextScopeProcessor._load_file_mode_cross_namespace_data(
                            needed_ns=needed_ns,
                            record=item,
                            agent_name=agent_name,
                            agent_indices=agent_indices,
                            file_path=file_path,
                            source_record=matched_source,
                            storage_backend=storage_backend,
                        )
                    )
                cross_ns_data = cross_ns_cache[cache_key]
            else:
                cross_ns_data = {}

            ordered: Dict[str, Any] = {}
            for ns, field, output_key in resolved:
                # Cross-namespace data takes priority for non-input namespaces.
                if ns in cross_ns_data and field in cross_ns_data[ns]:
                    ordered[output_key] = cross_ns_data[ns][field]
                # Input source (per-record content) — only when ns is actually
                # an input source.  Without this guard, an unresolved non-input
                # namespace (e.g. dep_b) would silently grab a same-named field
                # from the primary record, producing incorrect context.
                # When has_reliable_ns is False (content-key heuristic), we
                # allow the fallback for all refs since we can't distinguish
                # input namespaces from others.
                elif (not has_reliable_ns or ns in input_source_names) and field in content:
                    ordered[output_key] = content[field]
                # Field not found anywhere — skip silently (logged at debug).
                else:
                    logger.debug(
                        "[FILE OBSERVE] Field '%s' (ns='%s') not found for action '%s'. "
                        "content keys=%s, cross_ns keys=%s.",
                        field,
                        ns,
                        agent_name,
                        list(content.keys()),
                        list(cross_ns_data.get(ns, {}).keys()),
                    )

            filtered.append(ordered)

        return filtered
