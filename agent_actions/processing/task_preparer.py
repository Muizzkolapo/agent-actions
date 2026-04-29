"""Unified task preparation for both batch and online modes."""

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from agent_actions.input.preprocessing.filtering.evaluator import GuardBehavior
from agent_actions.processing.prepared_task import (
    GuardStatus,
    PreparationContext,
    PreparedTask,
)
from agent_actions.record.state import (
    CASCADE_BLOCKING_STATES,
    RESETTABLE_DOWNSTREAM_STATES,
    RecordState,
)
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

        if isinstance(item, dict):
            self._reset_state_for_downstream(item)

        if self._is_upstream_unprocessed(item):
            target_id = existing_target_id or self._generate_target_id()
            source_guid = item.get("source_guid") if isinstance(item, dict) else None
            return PreparedTask(
                target_id=target_id,
                source_guid=source_guid,
                original_content=get_existing_content(item) if isinstance(item, dict) else item,
                guard_status=GuardStatus.UPSTREAM_UNPROCESSED,
            )

        content, source_guid, source_snapshot = self._normalize_input(item, context)
        target_id = existing_target_id or self._generate_target_id()

        if context.is_first_stage:
            source_content = content
        else:
            source_content = self._get_source_content(source_guid, context)
            if source_content is None:
                source_content = content

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
            if prepared.source_guid is not None:
                context.storage_backend.write_prompt_trace(
                    action_name=context.agent_name,
                    record_id=prepared.source_guid,
                    compiled_prompt=prepared.formatted_prompt,
                    llm_context=json.dumps(prepared.llm_context, ensure_ascii=False, default=str),
                    model_name=context.agent_config.get("model"),
                    model_vendor=context.agent_config.get("model_vendor"),
                    run_mode=context.mode.value if context.mode else None,
                )
            else:
                logger.warning(
                    "Skipping prompt trace: source_guid is None for action=%s",
                    context.agent_name,
                )

        return prepared

    def _normalize_input(
        self, item: Any, context: PreparationContext
    ) -> tuple[Any, str | None, Any | None]:
        """Normalize input to (content, source_guid, source_snapshot)."""
        if context.is_first_stage:
            source_guid: str | None
            if self._id_generator:
                source_guid = self._id_generator(item)
            else:
                source_guid = IDGenerator.generate_deterministic_source_guid(item)

            snapshot = self._prepare_source_snapshot(item)
            return item, source_guid, snapshot
        else:
            if isinstance(item, dict):
                content = item.get("content")
                if content is None:
                    # First-stage batch records may not have content wrapper yet —
                    # treat them like first-stage by extracting raw fields
                    source_guid = item.get("source_guid")
                    if not source_guid:
                        source_guid = IDGenerator.generate_deterministic_source_guid(item)
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

    def _get_source_content(
        self, source_guid: str | None, context: PreparationContext
    ) -> Any | None:
        """Look up source content by source_guid, or return None."""
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
        current_item: dict | None = None,
    ) -> dict[str, Any]:
        """Load full context (source, upstream, version, workflow) for guard and prompt."""
        from agent_actions.prompt.context.scope_builder import build_field_context_with_history

        field_context = build_field_context_with_history(
            agent_name=context.agent_name,
            agent_config=context.agent_config,
            agent_indices=context.agent_indices,
            source_content=source_content,
            version_context=context.version_context,
            workflow_metadata=context.workflow_metadata,
            current_item=current_item,
            context_scope=context.agent_config.get("context_scope"),
        )
        field_context.pop("_dependency_metadata", None)

        # Promote output_field values to top-level so guards can reference them directly.
        # E.g., if action "assess_severity" has output_field="severity", then
        # field_context["severity"] = field_context["assess_severity"]["severity"]
        # so guards can write `severity != "low"` instead of `assess_severity.severity != "low"`.
        if context.dependency_configs:
            for dep_name, dep_config in context.dependency_configs.items():
                if not dep_config or "output_field" not in dep_config:
                    continue
                of_name = dep_config["output_field"]
                dep_data = field_context.get(dep_name)
                # Unwrap single-item list (common storage shape for output_field actions)
                if isinstance(dep_data, list) and len(dep_data) == 1:
                    dep_data = dep_data[0]
                if isinstance(dep_data, dict) and of_name in dep_data:
                    if of_name not in field_context:
                        field_context[of_name] = dep_data[of_name]
                    else:
                        logger.warning(
                            "output_field '%s' from action '%s' collides with existing "
                            "field in context — use '%s.%s' in guard conditions instead",
                            of_name,
                            dep_name,
                            dep_name,
                            of_name,
                        )

        return field_context

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

    @staticmethod
    def _is_upstream_unprocessed(item: Any) -> bool:
        """Return True only for cascade-blocked records (FAILED/EXHAUSTED/CASCADE_SKIPPED)."""
        if not isinstance(item, dict):
            return False
        state = RecordState.from_record(item)
        return state in CASCADE_BLOCKING_STATES

    @staticmethod
    def _reset_state_for_downstream(item: dict[str, Any]) -> None:
        """Reset upstream-settled records to ACTIVE when used as downstream input."""
        state = RecordState.from_record(item)
        if state in RESETTABLE_DOWNSTREAM_STATES:
            item["_state"] = RecordState.ACTIVE.value

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
