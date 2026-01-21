"""
Context Scope Processor - Field flow control for LLM context and output.

Processes context_scope directives: static_data, observe, drop, passthrough.
"""
# Line-too-long: Complex data transformations require descriptive variable names
# Import-outside-toplevel: Avoid circular imports
# Broad-exception-caught: Intentional fallback behavior for data processing

import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from copy import deepcopy

logger = logging.getLogger(__name__)


class ContextScopeProcessor:
    """
    Processes context_scope configuration for field flow control.

    Special Namespaces:
        source: Original input data loaded from source files
        loop: Current iteration context in versioned actions
        workflow: Workflow metadata (name, version, run_id)
    """

    # Reserved namespaces that are not workflow actions
    SPECIAL_NAMESPACES = frozenset({"source", "loop", "workflow"})

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
            except ValueError:
                # Skip invalid references
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
            except ValueError:
                # Invalid reference format, skip
                continue

        return referenced_actions

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
        from agent_actions.errors import ConfigurationError

        # 1. Get explicit dependencies (input sources)
        # Support both 'dependencies' and 'depends_on' for backward compatibility
        deps = action_config.get("dependencies") or action_config.get("depends_on", [])
        if deps is None:
            input_sources = []
        elif isinstance(deps, str):
            input_sources = [deps]
        else:
            input_sources = list(deps)

        # 2. Parse context_scope to find all referenced actions
        context_scope = action_config.get("context_scope", {})
        referenced_actions = ContextScopeProcessor.extract_action_names_from_context_scope(
            context_scope
        )

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
            except ValueError:
                continue

        # 3. Auto-infer context sources (in context_scope but NOT in dependencies)
        # Exclude base names of field prefix patterns if they match loop iterations in dependencies
        potential_context_sources = referenced_actions - set(input_sources)
        context_sources = []
        for action in potential_context_sources:
            # Check if this is a field prefix base name and if dependencies contain loop iterations of it
            if action in field_prefix_base_names:
                # Check if any dependency starts with this base name (loop iteration pattern)
                has_loop_iterations = any(dep.startswith(f"{action}_") for dep in input_sources)
                if has_loop_iterations:
                    # This base name corresponds to loop iterations in dependencies
                    # Don't treat it as a separate context source
                    logger.debug(
                        f"[LOOP_FIELD_PREFIX] Excluding '{action}' from context sources - "
                        f"field prefix pattern matches loop iterations in dependencies"
                    )
                    continue
            context_sources.append(action)

        # 4. Expand version base names to their variants (e.g., extract_raw_qa -> [extract_raw_qa_1, extract_raw_qa_2, extract_raw_qa_3])
        # This handles version_consumption where context_scope references the base name
        def expand_version_base_names(
            action_list: List[str], is_context_sources: bool = False
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
                        # For context sources with wildcards, use field prefix pattern (action_)
                        # For dependencies or specific fields, expand to all variants
                        if is_context_sources and action in wildcard_actions:
                            # Version consumption with wildcard - use field prefix pattern
                            expanded.append(f"{action}_")
                            logger.debug(
                                f"[VERSION_FIELD_PREFIX] Converted version base name '{action}' with wildcard to field prefix '{action}_'"
                            )
                        else:
                            # Expand to all variants
                            expanded.extend(version_variants)
                            logger.debug(
                                f"[VERSION_EXPAND] Expanded version base name '{action}' to {version_variants}"
                            )
                    else:
                        # Not a version base name - keep as-is (will error in validation)
                        expanded.append(action)
            return expanded

        # Expand both input_sources and context_sources
        input_sources_expanded = expand_version_base_names(input_sources, is_context_sources=False)
        context_sources_expanded = expand_version_base_names(
            context_sources, is_context_sources=True
        )

        # 5. Validate all referenced actions exist in workflow
        # Skip validation for field prefix patterns (ending with _) and special namespaces
        all_deps = set(input_sources_expanded) | set(context_sources_expanded)
        for dep_action in all_deps:
            # Skip validation for loop field prefix patterns
            if dep_action.endswith("_"):
                continue

            # Skip validation for special reserved namespaces (source, loop, workflow)
            if dep_action in ContextScopeProcessor.SPECIAL_NAMESPACES:
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

        return action_data.get(field_name)

    @staticmethod
    def apply_context_scope(
        field_context: Dict, context_scope: Dict, static_data: Optional[Dict] = None
    ) -> Tuple[Dict, Dict, Dict]:
        """
        Apply context_scope rules, returning (prompt_context, llm_context, passthrough_fields).

        Adds SEED namespace from static_data parameter (namespace #3 per anatomy_action.md).
        This is the 5th namespace that gets added to field_context before filtering.

        Architecture:
        - field_context input: {source, {dep_name}, loop, workflow}
        - Add: {seed} from static_data parameter
        - Apply context_scope: observe/passthrough/drop
        - Return: prompt_context, llm_context, passthrough_fields
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
        for field_ref in context_scope.get("drop", []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Remove from prompt_context
                if action_name in prompt_context and isinstance(prompt_context[action_name], dict):
                    prompt_context[action_name].pop(field_name, None)

            except ValueError:
                # Invalid reference, skip silently
                continue

        # Process OBSERVE: Extract to llm_context, KEEP in prompt_context for template rendering
        for field_ref in context_scope.get("observe", []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Extract value from original field_context (before drop removed it)
                value = ContextScopeProcessor.extract_field_value(
                    field_context, action_name, field_name
                )

                if value is not None:
                    # Add to llm_context (flat dict with field names as keys)
                    llm_context[field_name] = value

                    # DO NOT remove from prompt_context - users need it for {{action.field}} template refs

            except ValueError:
                # Invalid reference, skip silently
                continue

        # Process PASSTHROUGH: Extract to passthrough_fields, remove from prompt_context
        for field_ref in context_scope.get("passthrough", []):
            try:
                action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)

                # Extract value from original field_context
                value = ContextScopeProcessor.extract_field_value(
                    field_context, action_name, field_name
                )

                if value is not None:
                    # Add to passthrough_fields (flat dict with field names as keys)
                    passthrough_fields[field_name] = value

            except ValueError:
                # Invalid reference, skip silently
                continue

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
    ) -> Optional[Dict]:
        """
        Load historical node data from saved files.

        Uses HistoricalNodeDataLoader with HistoricalDataRequest.
        Returns content dict or None if not found.
        """
        from agent_actions.input.context.historical_node_loader import (
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
        )

        return HistoricalNodeDataLoader.load_historical_node_data(request)

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
                from agent_actions.errors import ConfigurationError

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
            except ValueError:
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

                except ValueError:
                    # Invalid reference format, skip
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
                from agent_actions.errors import ConfigurationError

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
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        context_scope: Optional[Dict] = None,
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
            "loop": {...},          # Loop iteration info
            "workflow": {...},      # Workflow metadata
        }

        Args:
            contents: Legacy parameter (not used)
            agent_name: Name of the current action
            agent_config: Action configuration dict
            agent_indices: REQUIRED if action has dependencies. Maps action names to positions.
            dependency_configs: Legacy parameter (not used)
            source_content: Original input data for "source" namespace
            loop_context: Loop iteration info
            workflow_metadata: Workflow metadata
            current_item: Current record being processed (has lineage, content)
            file_path: Path to current file
            context_scope: Controls which fields to load (progressive data exposure)

        Returns:
            Dict with namespaces: source, {dep_names}, loop, workflow

        Raises:
            ConfigurationError: If action has dependencies but agent_indices not provided

        Progressive Data Exposure:
        - context_scope.observe: ["dep.field1", "dep.*"] -> Controls what gets loaded
        - context_scope.passthrough: ["dep.field2"] -> Also loaded (needed for output)
        - Undeclared fields never enter memory
        """
        from agent_actions.input.context.historical_node_loader import (
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

        # 2. DEPENDENCY namespaces - separate input sources from context sources
        if agent_config and agent_indices and current_item and file_path:
            # BATCH MODE - Use auto-inferred context dependencies
            workflow_actions = list(agent_indices.keys())

            # Infer input sources vs context sources
            input_sources, context_sources = ContextScopeProcessor.infer_dependencies(
                agent_config, workflow_actions, agent_name
            )

            logger.debug(
                f"[AUTO-INFER] Action '{agent_name}': "
                f"input_sources={input_sources}, context_sources={context_sources}"
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

                for input_source_name in input_sources:
                    allowed_fields = allowed_fields_map.get(input_source_name)

                    if allowed_fields is None:
                        # Wildcard: Load all fields
                        field_context[input_source_name] = input_data
                        logger.debug(
                            f"[INPUT SOURCE] Loaded '{input_source_name}' with ALL {len(input_data)} fields "
                            f"from current_item (wildcard)"
                        )
                    else:
                        # Specific fields: Filter
                        filtered_data = {
                            field: input_data[field]
                            for field in allowed_fields
                            if field in input_data
                        }
                        field_context[input_source_name] = filtered_data
                        logger.debug(
                            f"[INPUT SOURCE] Loaded '{input_source_name}' with {len(filtered_data)} fields "
                            f"from current_item: {list(filtered_data.keys())}"
                        )

            # 2b. CONTEXT SOURCES - Load via historical loader (lineage matching)
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
                    "[CONTEXT SOURCES] Loading %d context dependencies: %s",
                    len(context_sources),
                    context_sources,
                )

                for dep_name in context_sources:
                    # Skip special reserved namespaces - they're populated differently
                    if dep_name in ContextScopeProcessor.SPECIAL_NAMESPACES:
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
                    )

                    if historical_data is None:
                        logger.warning(
                            f"[CONTEXT SOURCE] Context dependency '{dep_name}' historical data not found. "
                            f"Lineage: {lineage}, source_guid: {source_guid}. "
                            f"Dependency will not be available in field_context."
                        )
                        continue

                    logger.debug(
                        f"[HISTORICAL LOAD] Loaded context dep '{dep_name}': fields={list(historical_data.keys())}"
                    )

                    # PROGRESSIVE DATA EXPOSURE: Filter to only allowed fields
                    allowed_fields = allowed_fields_map.get(dep_name)

                    if allowed_fields is None:
                        field_context[dep_name] = historical_data
                        logger.debug(
                            f"[CONTEXT SOURCE] Loaded '{dep_name}' with ALL {len(historical_data)} fields (wildcard)"
                        )
                    else:
                        filtered_data = {
                            field: historical_data[field]
                            for field in allowed_fields
                            if field in historical_data
                        }

                        missing_fields = set(allowed_fields) - set(historical_data.keys())
                        if missing_fields:
                            logger.warning(
                                f"[CONTEXT SOURCE] Dependency '{dep_name}': "
                                f"context_scope declares fields {missing_fields} but not found. "
                                f"Available fields: {list(historical_data.keys())}"
                            )

                        field_context[dep_name] = filtered_data
                        logger.debug(
                            f"[CONTEXT SOURCE] Loaded '{dep_name}' with {len(filtered_data)} fields: "
                            f"{list(filtered_data.keys())}"
                        )

        elif agent_config and agent_config.get("dependencies") and not agent_indices:
            # ERROR: Dependencies declared but no agent_indices provided
            # agent_indices is REQUIRED for dependency resolution (no fallbacks)
            from agent_actions.errors import ConfigurationError

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

        # 3. LOOP namespace - iteration info
        if loop_context:
            field_context["loop"] = loop_context
            logger.debug("Added 'loop' namespace")

        # 4. WORKFLOW namespace - metadata
        if workflow_metadata:
            field_context["workflow"] = workflow_metadata
            logger.debug("Added 'workflow' namespace")

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
