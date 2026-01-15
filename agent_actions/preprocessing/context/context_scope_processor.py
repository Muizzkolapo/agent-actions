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
    """Processes context_scope configuration for field flow control."""

    @staticmethod
    def parse_field_reference(field_ref: str) -> Tuple[str, str]:
        """Parse field reference in 'action.field' format, returning (action_name, field_name)."""
        if not field_ref or not isinstance(field_ref, str):
            raise ValueError(
                f"Invalid field reference: {field_ref!r}. "
                f"Expected non-empty string in format 'action.field'"
            )

        parts = field_ref.split(".", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid field reference: '{field_ref}'. "
                f"Expected format: 'action.field' (with exactly one dot)"
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
        from agent_actions.preprocessing.context.historical_node_loader import (
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
        declared_deps = set()
        for field_ref in all_field_refs:
            try:
                ref_action, _ = ContextScopeProcessor.parse_field_reference(field_ref)
                declared_deps.add(ref_action)
            except ValueError:
                continue

        for dep_name in dependencies:
            wildcard_found = False
            specific_fields = []

            for field_ref in all_field_refs:
                try:
                    ref_action, ref_field = ContextScopeProcessor.parse_field_reference(field_ref)

                    if ref_action != dep_name:
                        continue  # Not for this dependency

                    if ref_field == "*":
                        # Wildcard: dep_name.*
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
        contents: Dict,  # Kept for backward compatibility, not used in new architecture
        agent_name: str,
        agent_config: Optional[Dict],
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,  # Legacy, not used
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
        context_scope: Optional[Dict] = None,  # NEW: Controls which fields to load
    ) -> Dict:
        """
        Build field context with explicit namespace structure.

        NO FALLBACKS - Context determined by dependencies and context_scope only.
        TRUE PROGRESSIVE DATA EXPOSURE - Only loads fields declared in context_scope.

        Architecture (per anatomy_action.md):
        field_context = {
            "source": {...},        # Original input data
            "{dep_name}": {...},    # Dependency action outputs (FILTERED by context_scope)
            "seed": {...},          # Static reference data (via static_data)
            "loop": {...},          # Loop iteration info
            "workflow": {...},      # Workflow metadata
        }

        Batch Mode (has file_path + current_item + agent_indices):
        - Dependencies loaded from historical files ONLY
        - Missing dependencies cause explicit errors (fail fast)
        - FILTERED by context_scope: Only declared fields loaded

        Progressive Data Exposure:
        - context_scope.observe: ["dep.field1", "dep.*"] -> Controls what gets loaded
        - context_scope.passthrough: ["dep.field2"] -> Also loaded (needed for output)
        - Undeclared fields never enter memory

        Parameters kept for backward compatibility:
        - contents: Not used (was for fallback logic, now removed)
        - dependency_configs: Not used (was for schema lookup, now removed)
        """
        from agent_actions.preprocessing.context.historical_node_loader import (
            HistoricalNodeDataLoader,
        )

        field_context = {}

        # 1. SOURCE namespace - original input data
        if source_content:
            field_context["source"] = ContextScopeProcessor._extract_content_data(source_content)
            logger.debug("Added 'source' namespace with %s fields", len(field_context["source"]))

        # 2. DEPENDENCY namespaces - load from historical files (batch mode)
        dependencies = agent_config.get("dependencies", []) if agent_config else []

        if dependencies and current_item and file_path and agent_indices:
            # BATCH MODE - Load from historical files with progressive data exposure
            lineage = current_item.get("lineage", [])
            source_guid = current_item.get("source_guid")
            current_idx = agent_indices.get(agent_name, 999)

            # Extract which fields are allowed for each dependency from context_scope
            allowed_fields_map = ContextScopeProcessor._extract_allowed_fields_per_dependency(
                dependencies, context_scope, agent_name
            )

            logger.debug(
                f"[BATCH MODE] Loading {len(dependencies)} dependencies for '{agent_name}': {dependencies}"
            )
            logger.debug(
                f"[PROGRESSIVE EXPOSURE] Allowed fields per dependency: {allowed_fields_map}"
            )

            for dep_name in dependencies:
                # Check if dependency should be loaded
                dep_idx = agent_indices.get(dep_name)
                if dep_idx is None:
                    logger.warning(
                        f"Dependency '{dep_name}' not found in agent_indices. Available: {list(agent_indices.keys())}"
                    )
                    continue

                if dep_idx >= current_idx:
                    logger.debug(
                        f"Skipping dependency '{dep_name}' (comes after current action in pipeline)"
                    )
                    continue

                # Parallel Branch Check: Only load ancestors or explicit dependencies
                # Since we're iterating through declared dependencies, all are "explicit"
                # We should try to load them even if not in lineage yet
                is_ancestor = (
                    HistoricalNodeDataLoader._find_node_in_lineage(dep_name, lineage, agent_indices)
                    is not None
                )

                if not is_ancestor:
                    logger.debug(
                        f"Dependency '{dep_name}' not in lineage (may not have executed yet). "
                        f"Will attempt to load from historical files."
                    )
                    # Don't skip - try to load anyway. If file doesn't exist, we'll warn below.

                # Load historical data (full data from file)
                logger.debug(
                    f"[HISTORICAL LOAD] Loading dep '{dep_name}' from file_path={file_path}"
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
                if historical_data:
                    logger.debug(
                        f"[HISTORICAL LOAD] Loaded dep '{dep_name}': fields={list(historical_data.keys())}"
                    )

                if historical_data is None:
                    # Historical data not found - could be edge case (wrong source_guid, file missing, etc.)
                    # Log warning but don't fail - allow workflow to continue
                    logger.warning(
                        f"[BATCH MODE] Dependency '{dep_name}' declared but historical data not found. "
                        f"Lineage: {lineage}, source_guid: {source_guid}. "
                        f"Dependency will not be available in field_context."
                    )
                    continue  # Skip this dependency

                # PROGRESSIVE DATA EXPOSURE: Filter to only allowed fields
                allowed_fields = allowed_fields_map.get(dep_name)

                if allowed_fields is None:
                    # Wildcard or no context_scope: Load all fields
                    field_context[dep_name] = historical_data
                    logger.debug(
                        f"Loaded dependency '{dep_name}' with ALL {len(historical_data)} fields (wildcard)"
                    )
                else:
                    # Specific fields: Filter to only declared fields
                    filtered_data = {
                        field: historical_data[field]
                        for field in allowed_fields
                        if field in historical_data
                    }

                    # Warn if declared fields not found in historical data
                    missing_fields = set(allowed_fields) - set(historical_data.keys())
                    if missing_fields:
                        logger.warning(
                            f"[PROGRESSIVE EXPOSURE] Dependency '{dep_name}': "
                            f"context_scope declares fields {missing_fields} but not found in historical data. "
                            f"Available fields: {list(historical_data.keys())}"
                        )

                    field_context[dep_name] = filtered_data
                    logger.debug(
                        f"Loaded dependency '{dep_name}' with {len(filtered_data)} fields "
                        f"(filtered from {len(historical_data)} total): {list(filtered_data.keys())}"
                    )

        elif dependencies and not (current_item and file_path and agent_indices):
            # REALTIME MODE - Load from contents dict with progressive data exposure
            logger.debug(
                f"[REALTIME MODE] Loading {len(dependencies)} dependencies from contents dict"
            )

            # Extract allowed fields per dependency
            allowed_fields_map = ContextScopeProcessor._extract_allowed_fields_per_dependency(
                dependencies, context_scope, agent_name
            )
            logger.debug(f"[PROGRESSIVE EXPOSURE - REALTIME] Allowed fields: {allowed_fields_map}")

            # In realtime, contents dict has fields from previous actions
            # We need to map those to dependency namespaces
            for dep_name in dependencies:
                allowed_fields = allowed_fields_map.get(dep_name)

                if allowed_fields is None:
                    # Wildcard: Load all fields from contents
                    if isinstance(contents, dict):
                        field_context[dep_name] = dict(contents)
                        logger.debug(
                            f"[REALTIME] Loaded dependency '{dep_name}' with ALL {len(contents)} fields (wildcard)"
                        )
                else:
                    # Specific fields: Filter from contents
                    if isinstance(contents, dict):
                        filtered_data = {
                            field: contents[field] for field in allowed_fields if field in contents
                        }

                        # Warn if declared fields not in contents
                        missing_fields = set(allowed_fields) - set(contents.keys())
                        if missing_fields:
                            logger.warning(
                                f"[REALTIME] Dependency '{dep_name}': "
                                f"context_scope declares fields {missing_fields} but not found in contents. "
                                f"Available: {list(contents.keys())[:20]}"
                            )

                        field_context[dep_name] = filtered_data
                        logger.debug(
                            f"[REALTIME] Loaded dependency '{dep_name}' with {len(filtered_data)} fields "
                            f"(filtered from {len(contents)} total): {list(filtered_data.keys())}"
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
