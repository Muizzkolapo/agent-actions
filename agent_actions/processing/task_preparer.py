"""Unified task preparation for both batch and online modes."""

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from agent_actions.errors.validation import DataValidationError
from agent_actions.guards import GuardBehavior
from agent_actions.processing.prepared_task import (
    GuardStatus,
    PreparationContext,
    PreparedTask,
)
from agent_actions.record.state import CASCADE_BLOCKING_VALUES
from agent_actions.utils.content import get_existing_content
from agent_actions.utils.id_generation import IDGenerator

logger = logging.getLogger(__name__)


class TaskPreparer:
    """Unified task preparation for both batch and online modes."""

    def __init__(
        self,
        id_generator: Callable[[Any], str] | None = None,
    ):
        self._id_generator = id_generator

    def prepare(
        self,
        item: Any,
        context: PreparationContext,
        existing_target_id: str | None = None,
        skip_guard: bool = False,
    ) -> PreparedTask:
        """Prepare a single task: normalize, load context, evaluate guard, render prompt."""
        logger.debug(
            "Preparing task for %s (first_stage=%s, skip_guard=%s)",
            context.agent_name,
            context.is_first_stage,
            skip_guard,
        )

        if isinstance(item, dict) and item.get("_state") in CASCADE_BLOCKING_VALUES:
            target_id = existing_target_id or self._generate_target_id()
            return PreparedTask(
                target_id=target_id,
                source_guid=item.get("source_guid"),
                original_content=get_existing_content(item),
                guard_status=GuardStatus.UPSTREAM_UNPROCESSED,
            )

        content, source_guid, source_snapshot = self._normalize_input(item, context)
        target_id = existing_target_id or self._generate_target_id()

        if context.is_first_stage:
            source_content = content
        else:
            from agent_actions.processing.source_resolution import resolve_source_content

            source_content = resolve_source_content(
                item if isinstance(item, dict) else {},
                source_guid,
                context.source_data,
                action_name=context.agent_name,
            )

        current_item = item if isinstance(item, dict) else context.current_item
        field_context = self._load_full_context(content, source_content, context, current_item)

        guard_config = context.agent_config.get("guard")
        conditional_clause = context.agent_config.get("conditional_clause")

        if not skip_guard and (guard_config or conditional_clause):
            guard_result = self._evaluate_guard(
                content, guard_config, conditional_clause, field_context
            )
            if not guard_result.should_execute:
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
                    if guard_result.behavior == GuardBehavior.SKIP
                    else GuardStatus.FILTERED,
                    guard_behavior=guard_result.behavior,
                    prompt_context=field_context,
                )
            if guard_result.behavior == GuardBehavior.WARN:
                guard_clause = (
                    (guard_config.get("clause", "") if isinstance(guard_config, dict) else "")
                    or conditional_clause
                    or ""
                )
                logger.warning(
                    "[%s] Record failed guard condition (%s) — passing through (warn mode)",
                    context.agent_name,
                    guard_clause,
                )

        prep_result = self._render_prompt(content, context, field_context)

        prepared = PreparedTask(
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

        if context.storage_backend is not None:
            context.storage_backend.write_prompt_trace(
                action_name=context.agent_name,
                record_id=prepared.target_id,
                compiled_prompt=prepared.formatted_prompt,
                llm_context=json.dumps(prepared.llm_context, ensure_ascii=False, default=str),
                model_name=context.agent_config.get("model_name")
                or context.agent_config.get("model"),
                model_vendor=context.agent_config.get("model_vendor"),
                run_mode=context.mode.value if context.mode else None,
            )

        return prepared

    def _normalize_input(
        self, item: Any, context: PreparationContext
    ) -> tuple[Any, str | None, Any | None]:
        """Normalize input to (content, source_guid, source_snapshot)."""
        if context.is_first_stage:
            source_guid: str | None
            # Prefer existing source_guid (e.g., deterministic content-hash
            # assigned for checkpoint resume) over generating a new one.
            existing = item.get("source_guid") if isinstance(item, dict) else None
            if existing:
                source_guid = existing
            elif self._id_generator:
                source_guid = self._id_generator(item)
            else:
                source_guid = IDGenerator.derive_source_guid(item)

            snapshot = self._prepare_source_snapshot(item)
            return item, source_guid, snapshot
        else:
            if isinstance(item, dict):
                content = item.get("content")
                if content is None:
                    # First-stage records are stamped at ingestion (573 invariant); a blank
                    # one can't be re-derived here (the envelope would poison identity) —
                    # fail loud instead of fabricating a guid.
                    source_guid = item.get("source_guid")
                    if not source_guid:
                        raise DataValidationError(
                            "First-stage record reached task preparation without a "
                            "source_guid; it must be stamped at ingestion",
                            context={"keys": sorted(item.keys())},
                        )
                    snapshot = self._prepare_source_snapshot(item)
                    return item, source_guid, snapshot
                source_guid = item.get("source_guid")
                if source_guid == "":
                    source_guid = None  # Preserve None for fallback lineage/recovery
                return content, source_guid, item
            else:
                return item, None, None

    @staticmethod
    def _prepare_source_snapshot(item: Any) -> Any:
        """Prepare source snapshot, filtering out chunk_info metadata keys for dicts."""
        if isinstance(item, dict) and "chunk_info" in item:
            excluded_keys = ["target_id", "record_index", "chunk_index"]
            snapshot = {k: v for k, v in item.items() if k not in excluded_keys}
        else:
            snapshot = item.copy() if isinstance(item, dict) else item
        return snapshot

    def _load_full_context(
        self,
        content: Any,
        source_content: Any,
        context: PreparationContext,
        current_item: dict | None = None,
    ) -> dict[str, Any]:
        """Load full context (source, upstream, version, workflow) for guard and prompt.

        Delegates to the shared build_guard_context helper to ensure batch
        and online paths always build identical guard context.
        """
        from agent_actions.processing.guard_context import build_guard_context

        record = current_item if current_item is not None else {"content": content}
        return build_guard_context(
            record,
            agent_name=context.agent_name,
            agent_config=context.agent_config,
            agent_indices=context.agent_indices,
            source_content=source_content,
            version_context=context.version_context,
            workflow_metadata=context.workflow_metadata,
            dependency_configs=context.dependency_configs,
        )

    @staticmethod
    def _evaluate_guard(
        content: Any,
        guard_config: dict[str, Any] | None,
        conditional_clause: str | None,
        field_context: dict[str, Any],
    ):
        """Evaluate guard with full context; wraps non-dict content as ``{"_raw": content}``."""
        from agent_actions.input.preprocessing.filtering.evaluator import (
            get_guard_evaluator,
        )

        evaluator = get_guard_evaluator()

        if not isinstance(content, dict):
            logger.debug("Wrapping non-dict content as {'_raw': ...} for guard evaluation")
        return evaluator.evaluate(
            item=content if isinstance(content, dict) else {"_raw": content},
            guard_config=guard_config,
            context=field_context,
            conditional_clause=conditional_clause,
        )

    @staticmethod
    def _render_prompt(
        content: Any,
        context: PreparationContext,
        field_context: dict[str, Any],
    ):
        """Render prompt template using pre-loaded field context."""
        from agent_actions.prompt.service import PromptPreparationService

        return PromptPreparationService.prepare_prompt_with_field_context(
            agent_config=context.agent_config,
            agent_name=context.agent_name,
            contents=content if isinstance(content, dict) else {},
            mode=context.mode,
            field_context=field_context,
            tools_path=context.tools_path,
        )

    def _generate_target_id(self) -> str:
        """Generate a new target_id."""
        return IDGenerator.generate_target_id()


# Per-process singleton; assumes one workflow per process.
# Use reset_task_preparer() in tests.
_task_preparer: TaskPreparer | None = None
_task_preparer_lock = threading.Lock()


def get_task_preparer() -> TaskPreparer:
    """Get or create the global TaskPreparer instance (thread-safe)."""
    global _task_preparer
    if _task_preparer is None:
        with _task_preparer_lock:
            # Double-check after acquiring lock
            if _task_preparer is None:
                _task_preparer = TaskPreparer()
    return _task_preparer


def reset_task_preparer() -> None:
    """Reset the global TaskPreparer instance (for testing)."""
    global _task_preparer
    with _task_preparer_lock:
        _task_preparer = None
