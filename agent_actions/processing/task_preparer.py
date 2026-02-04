"""
Unified task preparation for both batch and online modes.

Part of Phase 2 (#890): Extract Shared PreparedTask Builder.

TaskPreparer provides a single code path for task preparation:
1. Normalize input format
2. Source content lookup
3. Load full context (upstream outputs, version, workflow)
4. Guard evaluation (ONE check with full context)
5. Prompt rendering (only for items that passed guard)

This ensures identical preparation behavior regardless of execution mode.
"""

import logging
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

from agent_actions.processing.prepared_task import (
    GuardStatus,
    PreparedTask,
    PreparationContext,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class TaskPreparer:
    """
    Unified task preparation for both batch and online modes.

    Extracts shared preparation logic from RecordProcessor and BatchTaskPreparator
    to ensure identical behavior regardless of execution mode.

    Guard evaluation happens ONCE with full context (upstream outputs, version,
    workflow, source). This is like a SQL WHERE clause - simple and predictable.

    Flow:
        1. Normalize input → 2. Source lookup → 3. Load context →
        4. Guard evaluation → 5. Prompt rendering (if passed)

    Example:
        preparer = TaskPreparer()
        context = PreparationContext(agent_config=config, agent_name="my_agent")

        prepared = preparer.prepare(item, context)

        if prepared.should_execute:
            # Execute LLM with prepared.formatted_prompt, prepared.llm_context
            pass
        elif prepared.is_passthrough:
            # Return original content (skip behavior)
            pass
        else:
            # Filtered out
            pass
    """

    def __init__(
        self,
        id_generator: Optional[Callable[[Any], str]] = None,
    ):
        """
        Initialize TaskPreparer.

        Args:
            id_generator: Optional custom ID generator function.
                Defaults to IDGenerator.generate_deterministic_source_guid.
        """
        self._id_generator = id_generator

    def prepare(
        self,
        item: Any,
        context: PreparationContext,
        existing_target_id: Optional[str] = None,
        skip_guard: bool = False,
    ) -> PreparedTask:
        """
        Prepare a single task for execution.

        Unified logic for both batch and online modes:
        1. Normalize input format (extract content, generate/extract source_guid)
        2. Source content lookup
        3. Load full context (upstream outputs, version, workflow, source)
        4. Guard evaluation with full context (ONE check)
        5. Prompt rendering (only for items that passed guard)

        Args:
            item: Input item (any type for first-stage, dict for subsequent-stage)
            context: PreparationContext with all required configuration
            existing_target_id: Optional pre-existing target_id (batch mode)
            skip_guard: Skip guard evaluation (for preflight validation)

        Returns:
            PreparedTask with all preparation results
        """
        # Step 1: Normalize input format
        content, source_guid, source_snapshot = self._normalize_input(item, context)
        target_id = existing_target_id or self._generate_target_id()

        # Step 2: Source content lookup
        # For first-stage, source_content is the content itself
        # For subsequent-stage, look up by source_guid, fall back to content if not found
        if context.is_first_stage:
            source_content = content
        else:
            source_content = self._get_source_content(source_guid, context)
            # Fall back to content if source lookup fails (common for batch without source data)
            if source_content is None:
                source_content = content

        # Step 3: Load full context (upstream outputs, version, workflow, source)
        # This context is used for BOTH guard evaluation and prompt rendering
        current_item = item if isinstance(item, dict) else context.current_item
        field_context = self._load_full_context(
            content, source_content, context, current_item
        )

        # Step 4: Guard evaluation with FULL context (ONE check)
        # Guards can reference upstream outputs (e.g., extract_facts.count > 5)
        guard_config = context.agent_config.get("guard")
        conditional_clause = context.agent_config.get("conditional_clause")

        if not skip_guard and (guard_config or conditional_clause):
            guard_result = self._evaluate_guard(
                content, guard_config, conditional_clause, field_context
            )
            if not guard_result.should_execute:
                # Guard filtered/skipped - return early WITHOUT rendering prompt
                return PreparedTask(
                    target_id=target_id,
                    source_guid=source_guid,
                    formatted_prompt="",  # Not rendered - item filtered
                    llm_context={},
                    passthrough_fields={},
                    original_content=content,
                    source_content=source_content,
                    source_snapshot=source_snapshot,
                    guard_status=GuardStatus.SKIPPED
                    if guard_result.behavior == "skip"
                    else GuardStatus.FILTERED,
                    guard_behavior=guard_result.behavior,
                    prompt_context=field_context,
                )

        # Step 5: Prompt rendering (only for items that passed guard)
        # Reuse the loaded field_context for efficiency
        prep_result = self._render_prompt(content, context, field_context)

        # All checks passed - return prepared task
        return PreparedTask(
            target_id=target_id,
            source_guid=source_guid,
            formatted_prompt=prep_result.formatted_prompt,
            llm_context=prep_result.llm_context,
            passthrough_fields=prep_result.passthrough_fields,
            original_content=content,
            source_content=source_content,
            source_snapshot=source_snapshot,
            guard_status=GuardStatus.PASSED,
            prompt_context=prep_result.prompt_context,
        )

    def _normalize_input(
        self, item: Any, context: PreparationContext
    ) -> Tuple[Any, Optional[str], Optional[Any]]:
        """
        Normalize input format.

        First-stage: raw input → generate source_guid, preserve snapshot
        Subsequent-stage: structured {content, source_guid} → extract fields

        Args:
            item: Input item (any type for first-stage, dict for subsequent-stage)
            context: PreparationContext

        Returns:
            Tuple of (content, source_guid, source_snapshot)
        """
        if context.is_first_stage:
            from agent_actions.utils.id_generation import IDGenerator

            if self._id_generator:
                source_guid = self._id_generator(item)
            else:
                source_guid = IDGenerator.generate_deterministic_source_guid(item)

            # Prepare snapshot with chunk_info filtering
            snapshot = self._prepare_source_snapshot(item)
            return item, source_guid, snapshot
        else:
            # Subsequent-stage expects dict with content/source_guid
            if isinstance(item, dict):
                content = item.get("content", item)
                source_guid = item.get("source_guid")
                if source_guid == "":
                    source_guid = None  # Preserve None for fallback lineage/recovery
                return content, source_guid, item
            else:
                # Non-dict input in subsequent-stage: treat as raw content
                return item, None, None  # None triggers fallback lineage/recovery

    def _prepare_source_snapshot(self, item: Any) -> Any:
        """
        Prepare source snapshot for first-stage processing.

        Preserves original StagingProcessor behavior:
        - Filters out chunk_info metadata keys for dicts
        - Returns item as-is for non-dict types

        Args:
            item: Input item (any type)

        Returns:
            Filtered snapshot (dict) or original item (for non-dict types)
        """
        if isinstance(item, dict) and "chunk_info" in item:
            excluded_keys = ["target_id", "record_index", "chunk_index"]
            snapshot = {k: v for k, v in item.items() if k not in excluded_keys}
        else:
            snapshot = item.copy() if isinstance(item, dict) else item
        return snapshot

    def _get_source_content(
        self, source_guid: Optional[str], context: PreparationContext
    ) -> Optional[Any]:
        """
        Get source content for prompt preparation.

        Args:
            source_guid: Source GUID to lookup
            context: PreparationContext

        Returns:
            Source content if found, None otherwise
        """
        if source_guid is None:
            return None

        if not context.source_data:
            logger.debug(
                "Source data not available for %s; cannot look up source_guid=%s",
                context.agent_name,
                source_guid,
            )
            return None

        from agent_actions.input.preprocessing.transformation.transformer import (
            DataTransformer,
        )

        source_content = DataTransformer.get_content_by_source_guid(
            context.source_data, source_guid
        )
        if source_content is None:
            logger.debug(
                "Could not resolve source content for %s (%s source_data items)",
                context.agent_name,
                len(context.source_data),
            )
        return source_content

    def _load_full_context(
        self,
        content: Any,
        source_content: Any,
        context: PreparationContext,
        current_item: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Load full context including upstream action outputs.

        This context is used for BOTH guard evaluation and prompt rendering,
        ensuring guards have access to all fields they might reference.

        Args:
            content: Current content
            source_content: Source content for {{ source.* }} templates
            context: PreparationContext
            current_item: Optional full item dict for historical data loading

        Returns:
            Dict with all namespaces: source, upstream actions, version, workflow
        """
        from agent_actions.prompt.context.scope import ContextScopeProcessor

        # Load full context via ContextScopeProcessor
        # This loads upstream action outputs via historical lookup
        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents=content if isinstance(content, dict) else {},
            agent_name=context.agent_name,
            agent_config=context.agent_config,
            agent_indices=context.agent_indices,
            dependency_configs=context.dependency_configs,
            source_content=source_content,
            version_context=context.version_context,
            workflow_metadata=context.workflow_metadata,
            current_item=current_item,
            file_path=context.file_path,
            context_scope=context.agent_config.get("context_scope"),
            output_directory=context.output_directory,
            storage_backend=context.storage_backend,
        )

        return field_context

    def _evaluate_guard(
        self,
        content: Any,
        guard_config: Optional[Dict[str, Any]],
        conditional_clause: Optional[str],
        field_context: Dict[str, Any],
    ):
        """
        Evaluate guard with full context.

        Guards can reference any field available in field_context:
        - source.* (original input)
        - upstream_action.field (e.g., extract_facts.count)
        - version.* (iteration context)
        - workflow.* (workflow metadata)
        - Top-level content fields

        Args:
            content: Original content (for item parameter)
            guard_config: Guard configuration dict
            conditional_clause: Optional legacy conditional clause
            field_context: Full context with all namespaces

        Returns:
            GuardResult with should_execute and behavior
        """
        from agent_actions.input.preprocessing.filtering.evaluator import (
            get_guard_evaluator,
        )

        evaluator = get_guard_evaluator()

        # Evaluate with full context
        return evaluator.evaluate_with_context(
            item=content if isinstance(content, dict) else {"_raw": content},
            guard_config=guard_config,
            context=field_context,
            conditional_clause=conditional_clause,
        )

    def _render_prompt(
        self,
        content: Any,
        context: PreparationContext,
        field_context: Dict[str, Any],
    ):
        """
        Render prompt template using pre-loaded context.

        Args:
            content: Current content
            context: PreparationContext
            field_context: Pre-loaded context (reused from guard evaluation)

        Returns:
            PromptPreparationResult with formatted_prompt, llm_context,
            passthrough_fields, prompt_context
        """
        from agent_actions.prompt.service import PromptPreparationService

        # Determine mode based on explicit flag
        mode = "batch" if context.is_batch_mode else "realtime"

        # Use prepare_prompt_with_preloaded_context if available,
        # otherwise fall back to standard preparation
        return PromptPreparationService.prepare_prompt_with_field_context(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            contents=content if isinstance(content, dict) else {},
            mode=mode,
            field_context=field_context,
            tools_path=context.tools_path,
        )

    def _generate_target_id(self) -> str:
        """Generate a new target_id."""
        from agent_actions.utils.id_generation import IDGenerator

        return IDGenerator.generate_target_id()


# Module-level singleton for convenience
_task_preparer: Optional[TaskPreparer] = None


def get_task_preparer() -> TaskPreparer:
    """Get or create the global TaskPreparer instance."""
    global _task_preparer
    if _task_preparer is None:
        _task_preparer = TaskPreparer()
    return _task_preparer


def reset_task_preparer() -> None:
    """Reset the global TaskPreparer instance (for testing)."""
    global _task_preparer
    _task_preparer = None
