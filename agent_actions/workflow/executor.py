"""Single action execution with batch support."""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from rich.console import Console

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors import get_error_detail
from agent_actions.llm.providers.usage_tracker import get_last_usage
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ActionSkipEvent,
    BatchCompleteEvent,
    BatchSubmittedEvent,
)
from agent_actions.record.reasons import ALL_VERSIONS_FILTERED, GUARD_FILTERED_ALL
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.tooling.docs.run_tracker import ActionCompleteConfig
from agent_actions.utils.constants import DEFAULT_ACTION_KIND
from agent_actions.workflow.managers.output import AllVersionsFilteredError
from agent_actions.workflow.managers.state import COMPLETED_STATUSES, ActionStatus

logger = logging.getLogger(__name__)

# Prefix used in skip_reason for cascade failures.  The renderer checks
# this prefix to distinguish "blocked by upstream" from "guard-filtered".
UPSTREAM_SKIP_PREFIX = "Upstream dependency"

# Reason string for WHERE-clause skip (action skipped, record unchanged).
WHERE_SKIP_REASON = "WHERE clause — action skipped"


def _compute_action_config_hash(
    action_config: ActionConfigDict,
) -> str:
    """Compute a deterministic hash of semantically-meaningful action config.

    Covers: prompt reference, model, schema reference, guard clause + behavior.
    Changes to these fields invalidate prior results.
    Cosmetic fields (description, tags) are excluded.
    """
    raw_guard: Any = action_config.get("guard") or {}
    guard: dict[str, str] = (
        {"clause": raw_guard, "behavior": "skip"} if isinstance(raw_guard, str) else raw_guard
    )

    hash_input = {
        "prompt": action_config.get("prompt", ""),
        "model": action_config.get("model", ""),
        "schema": action_config.get("schema", ""),
        "guard_clause": guard.get("clause", ""),
        "guard_behavior": guard.get("behavior", ""),
    }

    serialized = json.dumps(hash_input, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecutorDependencies:
    """Dependencies for ActionExecutor."""

    action_runner: Any
    state_manager: Any
    skip_evaluator: Any
    batch_manager: Any
    output_manager: Any

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"action_runner={self.action_runner.__class__.__name__}, "
            f"state_manager={self.state_manager.__class__.__name__})"
        )


@dataclass
class ExecutionMetrics:
    """Metrics from action execution."""

    duration: float = 0.0
    tokens: dict[str, int] | None = None
    model_vendor: str | None = None
    model_name: str | None = None
    files_processed: int = 0
    # Number of target records this specific execution wrote (after - before
    # snapshot). Stays at the default 0 for paths that don't write target
    # rows: batch_submitted (job still pending), WHERE-skip (no data written),
    # guard-all-filtered SKIPPED, FAILED, and cached completions discovered
    # by _check_prior_output (this execution didn't run the action).
    record_count: int = 0


@dataclass
class ActionRunParams:
    """Parameters for action execution."""

    action_name: str
    action_idx: int
    action_config: ActionConfigDict
    is_last_action: bool
    start_time: datetime


@dataclass
class ActionExecutionResult:
    """Result of action execution."""

    success: bool
    output_folder: str | None = None
    status: ActionStatus = ActionStatus.COMPLETED
    error: Exception | None = None
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)

    def __post_init__(self) -> None:
        # Defensive: coerce None back to default if a caller passes metrics=None
        if self.metrics is None:  # type: ignore[comparison-overlap]  # defensive
            object.__setattr__(self, "metrics", ExecutionMetrics())  # type: ignore[unreachable]

    # Backward compatibility properties
    @property
    def duration(self) -> float:
        """Return duration from metrics."""
        return self.metrics.duration

    @property
    def tokens(self) -> dict[str, int] | None:
        """Return tokens from metrics."""
        return self.metrics.tokens

    @property
    def model_vendor(self) -> str | None:
        """Return model_vendor from metrics."""
        return self.metrics.model_vendor

    @property
    def model_name(self) -> str | None:
        """Return model_name from metrics."""
        return self.metrics.model_name

    @property
    def files_processed(self) -> int:
        """Return files_processed from metrics."""
        return self.metrics.files_processed

    # NOTE: no record_count property.  Callers must use result.metrics.record_count
    # directly — a property here added a second access path with no production
    # caller and obscured the source of truth.

    def __repr__(self):
        return (
            f"ActionExecutionResult(success={self.success}, "
            f"status={self.status}, duration={self.metrics.duration:.2f})"
        )


class ActionExecutor:
    """Executes individual actions with full lifecycle management."""

    def __init__(self, deps: ExecutorDependencies, *, console: Console | None = None):
        """Initialize action executor."""
        self.deps = deps
        self.console = console or Console()
        self.run_tracker: Any | None = None
        self.run_id: str | None = None

    def __eq__(self, other):
        if not isinstance(other, ActionExecutor):
            return False
        return self.deps == other.deps

    @staticmethod
    def _completion_metadata(action_config: ActionConfigDict) -> dict[str, Any]:
        """Build metadata dict for completed action status."""
        cfg: dict[str, Any] = action_config  # type: ignore[assignment]
        return {
            "record_limit": cfg.get("record_limit"),
            "file_limit": cfg.get("file_limit"),
            "config_hash": _compute_action_config_hash(action_config),
        }

    def _maybe_invalidate_completed_status(
        self, action_name: str, action_config: ActionConfigDict, current_status: ActionStatus
    ) -> ActionStatus:
        """Reset to pending if limit or semantic config changed since last completion."""
        if current_status not in COMPLETED_STATUSES:
            return current_status
        details = self.deps.state_manager.get_status_details(action_name)

        limits_changed = details.get("record_limit") != action_config.get(
            "record_limit"
        ) or details.get("file_limit") != action_config.get("file_limit")

        config_hash = _compute_action_config_hash(action_config)
        stored_hash = details.get("config_hash")
        config_changed = stored_hash is not None and stored_hash != config_hash

        if limits_changed or config_changed:
            reason = (
                "limit config" if limits_changed else "action config (prompt/model/schema/guard)"
            )
            logger.info("%s changed for %s, resetting to pending", reason, action_name)
            self.deps.state_manager.update_status(action_name, ActionStatus.PENDING)
            storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
            if storage_backend is not None:
                storage_backend.clear_disposition(action_name)
            return ActionStatus.PENDING
        return current_status

    def verify_completion_status(self, action_name: str) -> bool:
        """Return True if the action has valid output and should be skipped.

        Resets to 'pending' (and returns False) if the action is marked
        completed but has no output in the storage backend.  Called from
        the level executor before filtering pending actions so that stale
        'completed' upstreams are re-run before their dependents need them.
        """
        should_skip, _ = self._verify_completion_status(action_name)
        return should_skip

    def _verify_completion_status(
        self, action_name: str
    ) -> tuple[bool, ActionExecutionResult | None]:
        """Verify a completed action has actual output in storage.

        Returns (should_skip, result). If should_skip is False, action is re-run.
        """
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is None:
            logger.warning(
                "No storage backend available verifying %s — returning record_count=0",
                action_name,
            )
            return (
                True,
                ActionExecutionResult(
                    success=True,
                    status=ActionStatus.COMPLETED,
                    metrics=ExecutionMetrics(duration=0.0, record_count=0),
                ),
            )

        try:
            return self._check_prior_output(storage_backend, action_name)
        except Exception as e:
            logger.warning(
                "Failed to verify output for %s, resetting to pending: %s",
                action_name,
                e,
                exc_info=True,
            )
            self.deps.state_manager.update_status(action_name, ActionStatus.PENDING)
            return (False, None)

    def _check_prior_output(
        self, storage_backend: Any, action_name: str
    ) -> tuple[bool, ActionExecutionResult | None]:
        """Check if prior run left valid output or a blocking disposition."""
        # Disposition is authoritative — a failed/skipped action must re-run
        # even if partial output exists.
        for disp in (DISPOSITION_FAILED, DISPOSITION_SKIPPED):
            if storage_backend.has_disposition(action_name, disp, record_id=NODE_LEVEL_RECORD_ID):
                logger.info("Action %s has %s from prior run — re-running", action_name, disp)
                storage_backend.clear_disposition(action_name, disp, record_id=NODE_LEVEL_RECORD_ID)
                self.deps.state_manager.update_status(action_name, ActionStatus.PENDING)
                return (False, None)

        # The cached-completion path discovered an action that already
        # finished in a prior run.  This execution did NOT run the action,
        # so the per-execution record_count is 0 by definition — the
        # ExecutionMetrics default is correct.  (Previously this called
        # _count_output_records on every pending action's cold-start path,
        # which both ran a whole-DB stats query per discarded result AND
        # reported the cumulative SUM instead of the per-execution delta.)
        def _completed_result() -> tuple[bool, ActionExecutionResult]:
            return (
                True,
                ActionExecutionResult(
                    success=True,
                    status=ActionStatus.COMPLETED,
                    metrics=ExecutionMetrics(duration=0.0, record_count=0),
                ),
            )

        if storage_backend.list_target_files(action_name):
            return _completed_result()

        # No target files. Check if the action intentionally produced no
        # output (guard-filtered all records, WHERE-skipped, etc.) by
        # looking for a node-level terminal disposition that is NOT
        # FAILED/SKIPPED (those were already handled above).
        for disp in (
            DISPOSITION_FILTERED,
            DISPOSITION_PASSTHROUGH,
            DISPOSITION_SUCCESS,
            DISPOSITION_UNPROCESSED,
        ):
            if storage_backend.has_disposition(action_name, disp, record_id=NODE_LEVEL_RECORD_ID):
                logger.info(
                    "Action %s has no output but node-level %s — intentional, skipping re-run",
                    action_name,
                    disp,
                )
                return _completed_result()

        logger.info("Action %s completed but no output in storage — re-running", action_name)
        self.deps.state_manager.update_status(action_name, ActionStatus.PENDING)
        return (False, None)

    def _handle_action_skip(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle action skip due to WHERE clause condition.

        With the additive content model, skip means "add nothing to the
        record."  The record already carries all upstream namespaces, so
        there is no data to copy forward and no disposition to write —
        the action simply completes with status COMPLETED.
        """
        # No disposition written: the record is unchanged, downstream
        # proceeds normally reading existing namespaces.
        self.deps.state_manager.update_status(
            action_name, ActionStatus.COMPLETED, **self._completion_metadata(action_config)
        )

        duration = (datetime.now() - start_time).total_seconds()
        total_actions = (
            len(self.deps.action_runner.execution_order)
            if hasattr(self.deps.action_runner, "execution_order")
            else 0
        )
        fire_event(
            ActionSkipEvent(
                action_name=action_name,
                action_index=action_idx,
                total_actions=total_actions,
                skip_reason=WHERE_SKIP_REASON,
                mode=action_config.get("run_mode", ""),
            )
        )

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=action_name,
                status="success",
                duration_seconds=duration,
                skip_reason=WHERE_SKIP_REASON,
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=True, status=ActionStatus.COMPLETED, metrics=ExecutionMetrics(duration=duration)
        )

    def _track_action_start(self, params: ActionRunParams) -> None:
        """Track action start if run_tracker is available."""
        if self.run_tracker is not None and self.run_id is not None:
            model_vendor = params.action_config.get("model_vendor", "")
            action_kind = params.action_config.get("kind", "")

            if model_vendor == "tool" or action_kind == "tool":
                action_type = "tool"
            elif model_vendor == "hitl" or action_kind == "hitl":
                action_type = "hitl"
            else:
                action_type = DEFAULT_ACTION_KIND

            self.run_tracker.record_action_start(
                run_id=self.run_id,
                action_name=params.action_name,
                action_type=action_type,
                action_config=params.action_config,
            )

    def _handle_run_success(
        self,
        params: ActionRunParams,
        output_folder: str,
        duration: float,
        batch_status: str | None,
        pre_run_count: int,
    ) -> ActionExecutionResult:
        """Handle successful action run result.

        ``pre_run_count`` is the storage-backend record count for this action
        captured BEFORE the runner executed.  The delta against the post-run
        snapshot is what this execution actually wrote — using
        ``get_storage_stats`` directly would inflate on resume / re-run when
        prior runs left rows on different paths.
        """
        if batch_status == "batch_submitted":
            self.deps.state_manager.update_status(
                params.action_name,
                ActionStatus.BATCH_SUBMITTED,
                batch_submitted_at=datetime.now().isoformat(),
            )
            fire_event(BatchSubmittedEvent(action_name=params.action_name))
            return ActionExecutionResult(
                success=True,
                status=ActionStatus.BATCH_SUBMITTED,
                metrics=ExecutionMetrics(duration=duration),
            )

        if batch_status == "passthrough":
            self.deps.state_manager.update_status(
                params.action_name,
                ActionStatus.COMPLETED,
                **self._completion_metadata(params.action_config),
            )
            logger.info(
                "Action completed (passthrough)",
                extra={"action_name": params.action_name, "duration": duration},
            )
            return ActionExecutionResult(
                success=True,
                output_folder=output_folder,
                status=ActionStatus.COMPLETED,
                metrics=ExecutionMetrics(
                    duration=duration,
                    record_count=self._records_written_this_run(params.action_name, pre_run_count),
                ),
            )

        final_status = self._resolve_completion_status(params.action_name)

        if final_status == ActionStatus.SKIPPED:
            return self._handle_guard_all_filtered(params, output_folder, duration)

        if final_status == ActionStatus.FAILED:
            return self._finalize_total_failure(params.action_name, duration, output_folder)

        self.deps.state_manager.update_status(
            params.action_name,
            final_status,
            execution_time=duration,
            **self._completion_metadata(params.action_config),
        )
        tokens = get_last_usage()
        self._track_action_complete(params.action_name, duration, final_status, tokens=tokens)

        return ActionExecutionResult(
            success=True,
            output_folder=output_folder,
            status=final_status,
            metrics=ExecutionMetrics(
                duration=duration,
                tokens=tokens,
                model_vendor=params.action_config.get("model_vendor"),
                model_name=params.action_config.get("model_name"),
                files_processed=0,
                record_count=self._records_written_this_run(params.action_name, pre_run_count),
            ),
        )

    def _count_records_for_action(self, action_name: str) -> int:
        """Return the storage-backend record count for ``action_name``.

        Raises ``RuntimeError`` if the storage backend is unavailable or the
        underlying query / value parse fails.  This is called immediately
        before and after running an action so the delta yields the
        per-execution record count.  A silent fallback to 0 here would let a
        broken telemetry path masquerade as "action wrote nothing," exactly
        the failure mode spec 554 is eliminating.
        """
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is None:
            raise RuntimeError(
                f"Cannot count records for {action_name!r}: no storage backend on action_runner"
            )
        try:
            stats = storage_backend.get_storage_stats()
        except Exception as e:
            raise RuntimeError(
                f"Storage backend get_storage_stats() failed while counting "
                f"records for {action_name!r}: {e}"
            ) from e
        nodes = stats.get("nodes", {}) if isinstance(stats, dict) else {}
        raw = nodes.get(action_name, 0)
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError) as e:
            raise RuntimeError(
                f"Storage backend returned non-integer record_count {raw!r} "
                f"for {action_name!r}: {e}"
            ) from e

    def _records_written_this_run(self, action_name: str, pre_run_count: int) -> int:
        """Compute records written this execution as (after - before).

        Clamped at 0 — a negative delta would mean rows were deleted during
        the run, which is not a meaningful "records produced by this
        execution" signal.
        """
        after = self._count_records_for_action(action_name)
        delta = after - pre_run_count
        return delta if delta > 0 else 0

    def _handle_guard_all_filtered(
        self,
        params: ActionRunParams,
        output_folder: str,
        duration: float,
    ) -> ActionExecutionResult:
        """Handle the case where all records were guard-filtered (action resolves as SKIPPED)."""
        self.deps.state_manager.update_status(
            params.action_name,
            ActionStatus.SKIPPED,
            execution_time=duration,
            skip_reason=GUARD_FILTERED_ALL,
        )
        total_actions = (
            len(self.deps.action_runner.execution_order)
            if hasattr(self.deps.action_runner, "execution_order")
            else 0
        )
        fire_event(
            ActionSkipEvent(
                action_name=params.action_name,
                action_index=params.action_idx,
                total_actions=total_actions,
                skip_reason=GUARD_FILTERED_ALL,
                mode=params.action_config.get("run_mode", ""),
            )
        )
        self._track_action_complete(
            params.action_name, duration, ActionStatus.SKIPPED, skip_reason=GUARD_FILTERED_ALL
        )
        return ActionExecutionResult(
            success=True,
            output_folder=output_folder,
            status=ActionStatus.SKIPPED,
            metrics=ExecutionMetrics(duration=duration),
        )

    def _handle_all_versions_filtered(
        self, params: ActionRunParams, avf: AllVersionsFilteredError
    ) -> ActionExecutionResult:
        """Cascade-skip a version-consumption action whose every branch was filtered.

        All version sources produced no output, so there is nothing to merge.
        Resolve the action as SKIPPED with reason=all_versions_filtered and let
        the pipeline continue instead of crashing.
        """
        duration = (datetime.now() - params.start_time).total_seconds()
        self.deps.state_manager.update_status(
            params.action_name,
            ActionStatus.SKIPPED,
            execution_time=duration,
            skip_reason=ALL_VERSIONS_FILTERED,
        )
        self._write_skipped_disposition(
            params.action_name,
            ALL_VERSIONS_FILTERED,
            detail=f"All version sources filtered: {avf.version_sources}",
        )
        total_actions = (
            len(self.deps.action_runner.execution_order)
            if hasattr(self.deps.action_runner, "execution_order")
            else 0
        )
        fire_event(
            ActionSkipEvent(
                action_name=params.action_name,
                action_index=params.action_idx,
                total_actions=total_actions,
                skip_reason=ALL_VERSIONS_FILTERED,
                mode=params.action_config.get("run_mode", ""),
            )
        )
        self._track_action_complete(
            params.action_name, duration, ActionStatus.SKIPPED, skip_reason=ALL_VERSIONS_FILTERED
        )
        logger.warning(
            "All version sources filtered for '%s' (%s) — cascade-skipping; no output produced.",
            params.action_name,
            avf.version_sources,
        )
        return ActionExecutionResult(
            success=True,
            status=ActionStatus.SKIPPED,
            metrics=ExecutionMetrics(duration=duration),
        )

    def _track_action_complete(
        self,
        action_name: str,
        duration: float,
        status: ActionStatus,
        *,
        tokens: dict[str, int] | None = None,
        skip_reason: str | None = None,
    ) -> None:
        """Record action completion in run_tracker if available."""
        if self.run_tracker is None or self.run_id is None:
            return
        if status == ActionStatus.SKIPPED:
            tracker_status = "skipped"
        elif status == ActionStatus.COMPLETED:
            tracker_status = "success"
        elif status == ActionStatus.FAILED:
            tracker_status = "failed"
        else:
            tracker_status = "partial"
        config = ActionCompleteConfig(
            run_id=self.run_id,
            action_name=action_name,
            status=tracker_status,
            duration_seconds=duration,
            tokens=tokens,
            skip_reason=skip_reason,
            files_processed=0,
        )
        self.run_tracker.record_action_complete(config=config)

    def _finalize_total_failure(
        self,
        action_name: str,
        duration: float,
        output_folder: str | None = None,
        *,
        execution_mode: str | None = None,
    ) -> ActionExecutionResult:
        """Handle total item-level failure: update state, write disposition, track, return result."""
        reason = f"Action '{action_name}' failed: all records produced errors"
        status_kwargs: dict[str, Any] = {
            "execution_time": duration,
            "error_message": reason,
        }
        if execution_mode is not None:
            status_kwargs["execution_mode"] = execution_mode
        self.deps.state_manager.update_status(action_name, ActionStatus.FAILED, **status_kwargs)
        self._write_failed_disposition(action_name, reason)
        self._track_action_complete(action_name, duration, ActionStatus.FAILED)
        return ActionExecutionResult(
            success=False,
            output_folder=output_folder,
            status=ActionStatus.FAILED,
            error=RuntimeError(reason),
            metrics=ExecutionMetrics(duration=duration),
        )

    def _write_failed_disposition(self, action_name: str, reason: str) -> None:
        """Write DISPOSITION_FAILED to storage so downstream and future runs detect the failure."""
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is not None:
            try:
                storage_backend.set_disposition(
                    action_name=action_name,
                    record_id=NODE_LEVEL_RECORD_ID,
                    disposition=DISPOSITION_FAILED,
                    reason=reason[:500],
                )
            except Exception as disp_err:
                logger.warning(
                    "Failed to write DISPOSITION_FAILED for %s: %s",
                    action_name,
                    disp_err,
                )

    def _write_skipped_disposition(
        self, action_name: str, reason: str, *, detail: str | None = None
    ) -> None:
        """Write DISPOSITION_SKIPPED to storage so downstream and future runs detect the skip."""
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is not None:
            try:
                storage_backend.set_disposition(
                    action_name=action_name,
                    record_id=NODE_LEVEL_RECORD_ID,
                    disposition=DISPOSITION_SKIPPED,
                    reason=reason[:500],
                    detail=detail[:500] if detail is not None else None,
                )
            except Exception as disp_err:
                logger.warning(
                    "Failed to write DISPOSITION_SKIPPED for %s: %s",
                    action_name,
                    disp_err,
                )

    def _resolve_completion_status(self, action_name: str) -> ActionStatus:
        """Classify action outcome: FAILED (all items failed), SKIPPED (all guard-filtered), COMPLETED_WITH_FAILURES (partial), or COMPLETED."""
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is None:
            return ActionStatus.COMPLETED
        if storage_backend.has_disposition(
            action_name, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        ):
            # Clear-on-execute guarantees this row is current-round: only
            # _handle_dependency_skip could have written it, so map directly to SKIPPED.
            logger.info(
                "Action '%s' had all records guard-filtered — marking as skipped",
                action_name,
            )
            return ActionStatus.SKIPPED
        item_failures = storage_backend.get_failed_items(action_name)
        if item_failures:
            if not storage_backend.has_successful_items(action_name):
                logger.error(
                    "Action '%s' failed: 0 successful outputs out of %d records. "
                    "Halting workflow — all downstream actions will be skipped.",
                    action_name,
                    len(item_failures),
                )
                self._log_failure_details(item_failures)
                return ActionStatus.FAILED
            logger.warning(
                "Action '%s' completed with %d item-level failure(s)",
                action_name,
                len(item_failures),
            )
            self._log_failure_details(item_failures)
            return ActionStatus.COMPLETED_WITH_FAILURES
        return ActionStatus.COMPLETED

    def _log_failure_details(self, item_failures: list[dict]) -> None:
        for failure in item_failures[:3]:
            record_id = failure.get("record_id", "unknown")[:8]
            reason = failure.get("reason", "unknown")[:100]
            logger.warning("  record_id: %s  reason: %s", record_id, reason)
        if len(item_failures) > 3:
            logger.warning("  ... and %d more failure(s)", len(item_failures) - 3)

    def _handle_run_failure(
        self, params: ActionRunParams, error: Exception
    ) -> ActionExecutionResult:
        """Handle action run failure."""
        duration = (datetime.now() - params.start_time).total_seconds()
        self.deps.state_manager.update_status(
            params.action_name,
            ActionStatus.FAILED,
            execution_time=duration,
            error_message=str(error),
        )
        self._write_failed_disposition(params.action_name, str(error))

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=params.action_name,
                status="failed",
                duration_seconds=duration,
                error=get_error_detail(error),
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=False,
            status=ActionStatus.FAILED,
            error=error,
            metrics=ExecutionMetrics(duration=duration),
        )

    def _check_upstream_health(
        self, action_name: str, action_config: ActionConfigDict
    ) -> str | None:
        """Return the name of a failed/skipped upstream dependency, or None if healthy.

        Checks explicit dependencies and version sources (for merge/reduce actions).
        """
        deps_to_check = self._collect_upstream_deps(action_name, action_config)
        if not deps_to_check:
            return None

        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        for dep in deps_to_check:
            if self.deps.state_manager.is_failed(dep) or self.deps.state_manager.is_skipped(dep):
                return dep
            if storage_backend and self._has_blocking_disposition(
                storage_backend, dep, action_name
            ):
                return dep
        return None

    def _collect_upstream_deps(
        self, action_name: str, action_config: ActionConfigDict
    ) -> list[str]:
        """Build list of upstream dependencies including version sources."""
        deps: list[str] = list(action_config.get("dependencies", []))

        # Version sources: {base}_{N} agents for merge/reduce actions
        vc_config = action_config.get("version_consumption_config")
        if vc_config and isinstance(vc_config, dict):
            source_base = vc_config.get("source")
            if source_base:
                prefix = f"{source_base}_"
                for action in self.deps.state_manager.execution_order:
                    if (
                        action.startswith(prefix)
                        and action[len(prefix) :].isdigit()
                        and action != action_name
                    ):
                        deps.append(action)
        return deps

    def _has_blocking_disposition(self, storage_backend: Any, dep: str, action_name: str) -> bool:
        """Check if dep has a blocking disposition (FAILED/SKIPPED without output).

        Stale dispositions (disposition set but output exists) are cleared as a
        defense-in-depth measure for reruns with lingering pre-Phase-5 state.
        """
        for disposition in (DISPOSITION_FAILED, DISPOSITION_SKIPPED):
            if not storage_backend.has_disposition(
                dep, disposition, record_id=NODE_LEVEL_RECORD_ID
            ):
                continue
            target_files = storage_backend.list_target_files(dep)
            if not target_files:
                return True
            # Stale: disposition exists but output also exists — clear it
            storage_backend.clear_disposition(dep, disposition, record_id=NODE_LEVEL_RECORD_ID)
            logger.warning(
                "Stale upstream %s disposition on '%s' — upstream has %d target file(s). "
                "Clearing; downstream '%s' will proceed.",
                disposition,
                dep,
                len(target_files),
                action_name,
            )
        return False

    def _handle_dependency_skip(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
        failed_dependency: str,
    ) -> ActionExecutionResult:
        """Handle action skip due to upstream dependency failure.

        State is set to ``"skipped"`` so transitive dependents also skip via
        ``is_skipped``.  ``success=True`` keeps independent branches alive.
        """
        dep_status = (
            "skipped" if self.deps.state_manager.is_skipped(failed_dependency) else "failed"
        )
        reason = f"{UPSTREAM_SKIP_PREFIX} '{failed_dependency}' {dep_status}"
        duration = (datetime.now() - start_time).total_seconds()
        self.deps.state_manager.update_status(
            action_name, ActionStatus.SKIPPED, skip_reason=reason, execution_time=duration
        )
        self._write_skipped_disposition(action_name, reason)
        total_actions = (
            len(self.deps.action_runner.execution_order)
            if hasattr(self.deps.action_runner, "execution_order")
            else 0
        )
        fire_event(
            ActionSkipEvent(
                action_name=action_name,
                action_index=action_idx,
                total_actions=total_actions,
                skip_reason=reason,
                mode=action_config.get("run_mode", ""),
            )
        )

        if self.run_tracker is not None and self.run_id is not None:
            config = ActionCompleteConfig(
                run_id=self.run_id,
                action_name=action_name,
                status="skipped",
                duration_seconds=duration,
                skip_reason=reason,
            )
            self.run_tracker.record_action_complete(config=config)

        return ActionExecutionResult(
            success=True, status=ActionStatus.SKIPPED, metrics=ExecutionMetrics(duration=duration)
        )

    def execute_action_sync(
        self,
        action_name: str,
        *,
        action_idx: int,
        action_config: ActionConfigDict,
        is_last_action: bool,
    ) -> ActionExecutionResult:
        """Execute a single action synchronously."""
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(action_name)

        logger.debug(
            "Action execution starting",
            extra={
                "operation": "execute_action_start",
                "action_name": action_name,
                "action_idx": action_idx,
                "current_status": current_status,
                "is_last_action": is_last_action,
            },
        )

        current_status = self._maybe_invalidate_completed_status(
            action_name, action_config, current_status
        )

        if current_status in COMPLETED_STATUSES:
            should_skip, result = self._verify_completion_status(action_name)
            if should_skip:
                if result is None:
                    raise RuntimeError(
                        f"Action '{action_name}' marked completed but _verify_completion_status returned no result"
                    )
                return result
            current_status = self.deps.state_manager.get_status(action_name)

        if current_status == ActionStatus.BATCH_SUBMITTED:
            return self._handle_batch_check(action_name, action_idx, action_config, start_time)

        # Circuit breaker: skip if any upstream dependency has failed.
        # Must run BEFORE get_previous_outputs to avoid reading corrupt data.
        failed_dep = self._check_upstream_health(action_name, action_config)
        if failed_dep is not None:
            return self._handle_dependency_skip(
                action_name, action_idx, action_config, start_time, failed_dep
            )

        previous_outputs = self.deps.output_manager.get_previous_outputs(action_idx)
        if self.deps.skip_evaluator.should_skip_action(action_config, previous_outputs):
            return self._handle_action_skip(action_name, action_idx, action_config, start_time)

        return self._execute_action_run(
            ActionRunParams(
                action_name=action_name,
                action_idx=action_idx,
                action_config=action_config,
                is_last_action=is_last_action,
                start_time=start_time,
            )
        )

    async def execute_action_async(
        self,
        action_name: str,
        *,
        action_idx: int,
        action_config: ActionConfigDict,
        is_last_action: bool,
    ) -> ActionExecutionResult:
        """Execute a single action asynchronously."""
        start_time = datetime.now()
        current_status = self.deps.state_manager.get_status(action_name)

        logger.debug(
            "Action execution starting",
            extra={
                "operation": "execute_action_start",
                "action_name": action_name,
                "action_idx": action_idx,
                "current_status": current_status,
                "is_last_action": is_last_action,
            },
        )

        current_status = self._maybe_invalidate_completed_status(
            action_name, action_config, current_status
        )

        if current_status in COMPLETED_STATUSES:
            should_skip, result = self._verify_completion_status(action_name)
            if should_skip:
                if result is None:
                    raise RuntimeError(
                        f"Action '{action_name}' marked completed but _verify_completion_status returned no result"
                    )
                return result
            current_status = self.deps.state_manager.get_status(action_name)

        if current_status == ActionStatus.BATCH_SUBMITTED:
            return await self._handle_batch_check_async(
                action_name, action_idx, action_config, start_time
            )

        # Circuit breaker: skip if any upstream dependency has failed.
        failed_dep = self._check_upstream_health(action_name, action_config)
        if failed_dep is not None:
            return self._handle_dependency_skip(
                action_name, action_idx, action_config, start_time, failed_dep
            )

        previous_outputs = self.deps.output_manager.get_previous_outputs(action_idx)
        if self.deps.skip_evaluator.should_skip_action(action_config, previous_outputs):
            return self._handle_action_skip(action_name, action_idx, action_config, start_time)

        return await self._execute_action_run_async(
            ActionRunParams(
                action_name=action_name,
                action_idx=action_idx,
                action_config=action_config,
                is_last_action=is_last_action,
                start_time=start_time,
            )
        )

    def _compute_batch_wall_clock(self, action_name: str, fallback: float) -> float:
        """Compute wall-clock time from batch submission to now.

        Falls back to *fallback* when no ``batch_submitted_at`` timestamp
        was persisted (e.g. jobs submitted before this feature was added).
        """
        details = self.deps.state_manager.get_status_details(action_name)
        submitted_at = details.get("batch_submitted_at")
        if submitted_at:
            try:
                submitted_dt = datetime.fromisoformat(submitted_at)
                return (datetime.now() - submitted_dt).total_seconds()
            except (ValueError, TypeError) as e:
                logger.debug("Could not parse submitted_at %r: %s", submitted_at, e)
        return fallback

    def _handle_batch_check(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle batch job status checking (synchronous)."""
        self.deps.state_manager.update_status(action_name, ActionStatus.CHECKING_BATCH)
        output_directory = self._batch_output_directory(action_name)

        pre_run_count = self._count_records_for_action(action_name)
        output_folder, batch_status = self.deps.batch_manager.handle_batch_agent(
            action_name, output_directory, action_config
        )

        duration = (datetime.now() - start_time).total_seconds()
        return self._resolve_batch_outcome(
            action_name, action_config, output_folder, batch_status, duration, pre_run_count
        )

    async def _handle_batch_check_async(
        self,
        action_name: str,
        action_idx: int,
        action_config: ActionConfigDict,
        start_time: datetime,
    ) -> ActionExecutionResult:
        """Handle batch job status checking (asynchronous)."""
        self.deps.state_manager.update_status(action_name, ActionStatus.CHECKING_BATCH)
        output_directory = self._batch_output_directory(action_name)

        pre_run_count = self._count_records_for_action(action_name)
        output_folder, batch_status = await asyncio.to_thread(
            self.deps.batch_manager.handle_batch_agent,
            action_name,
            output_directory,
            action_config,
        )

        duration = (datetime.now() - start_time).total_seconds()
        return self._resolve_batch_outcome(
            action_name, action_config, output_folder, batch_status, duration, pre_run_count
        )

    def _batch_output_directory(self, action_name: str) -> str:
        """Resolve the target output directory for a batch action."""
        workflow_name = self.deps.action_runner.workflow_name
        agent_io_path = Path(self.deps.action_runner.get_action_folder(workflow_name))
        return str(agent_io_path / "target" / action_name)

    def _resolve_batch_outcome(
        self,
        action_name: str,
        action_config: ActionConfigDict,
        output_folder: str | None,
        batch_status: str,
        duration: float,
        pre_run_count: int,
    ) -> ActionExecutionResult:
        """Map batch_manager result to status, events, and ActionExecutionResult.

        ``pre_run_count`` is the storage-backend record count captured BEFORE
        the batch result was processed.  Used for the per-execution delta —
        see ``_handle_run_success`` for the rationale.
        """
        if batch_status == "completed":
            wall_clock = self._compute_batch_wall_clock(action_name, duration)
            final_status = self._resolve_completion_status(action_name)

            if final_status == ActionStatus.FAILED:
                fire_event(
                    BatchCompleteEvent(
                        batch_id=action_config.get("batch_id", ""),
                        action_name=action_name,
                        total=1,
                        completed=0,
                        failed=1,
                        elapsed_time=wall_clock,
                    )
                )
                return self._finalize_total_failure(
                    action_name, wall_clock, output_folder, execution_mode="batch"
                )

            self.deps.state_manager.update_status(
                action_name,
                final_status,
                execution_time=wall_clock,
                execution_mode="batch",
                **self._completion_metadata(action_config),
            )
            fire_event(
                BatchCompleteEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    total=1,
                    completed=1,
                    failed=0,
                    elapsed_time=wall_clock,
                )
            )
            return ActionExecutionResult(
                success=True,
                output_folder=output_folder,
                status=final_status,
                metrics=ExecutionMetrics(
                    duration=wall_clock,
                    record_count=self._records_written_this_run(action_name, pre_run_count),
                ),
            )

        if batch_status == "in_progress":
            self.deps.state_manager.update_status(action_name, ActionStatus.BATCH_SUBMITTED)
            fire_event(
                BatchSubmittedEvent(
                    batch_id=action_config.get("batch_id", ""),
                    action_name=action_name,
                    request_count=0,
                    provider=action_config.get("model_vendor", ""),
                )
            )
            return ActionExecutionResult(
                success=True,
                status=ActionStatus.BATCH_SUBMITTED,
                metrics=ExecutionMetrics(duration=duration),
            )

        # Failed
        self.deps.state_manager.update_status(action_name, ActionStatus.FAILED)
        self._write_failed_disposition(action_name, f"Batch job for {action_name} failed")
        fire_event(
            BatchCompleteEvent(
                batch_id=action_config.get("batch_id", ""),
                action_name=action_name,
                total=1,
                completed=0,
                failed=1,
                elapsed_time=duration,
            )
        )
        return ActionExecutionResult(
            success=False,
            status=ActionStatus.FAILED,
            error=Exception(f"Batch job for {action_name} failed"),
            metrics=ExecutionMetrics(duration=duration),
        )

    def _clear_stale_node_disposition(self, action_name: str) -> None:
        """Enforce the invariant that NODE_LEVEL disposition reflects the current round only.

        Per-record dispositions (real source_guid keys) are unaffected — the
        clear is keyed on record_id.
        """
        storage_backend = getattr(self.deps.action_runner, "storage_backend", None)
        if storage_backend is None:
            return
        try:
            storage_backend.clear_disposition(
                action_name=action_name,
                record_id=NODE_LEVEL_RECORD_ID,
            )
        except Exception as err:
            logger.warning(
                "Failed to clear stale node-level disposition for %s: %s",
                action_name,
                err,
            )

    def _execute_action_run(self, params: ActionRunParams) -> ActionExecutionResult:
        """Execute action run (synchronous)."""
        self._clear_stale_node_disposition(params.action_name)
        self.deps.state_manager.update_status(params.action_name, ActionStatus.RUNNING)
        self._track_action_start(params)
        try:
            correlated_input = self.deps.output_manager.resolve_correlated_input(params.action_idx)
        except AllVersionsFilteredError as avf:
            return self._handle_all_versions_filtered(params, avf)

        # Snapshot must surface storage errors loudly (no silent 0 fallback).
        # Both pre-run and post-run snapshots are intentionally OUTSIDE the
        # except clause below: only failures from the user-supplied action
        # runner should be funneled through _handle_run_failure.
        pre_run_count = self._count_records_for_action(params.action_name)
        try:
            output_folder = self.deps.action_runner.run_action(
                params.action_config,
                params.action_name,
                None,
                params.action_idx,
                input_directories_override=correlated_input,
            )
        except Exception as e:
            return self._handle_run_failure(params, e)

        duration = (datetime.now() - params.start_time).total_seconds()
        batch_status = self._check_batch_submission(
            params.action_name,
            params.action_idx,
            configured_run_mode=params.action_config.get("run_mode"),
        )
        return self._handle_run_success(
            params, output_folder, duration, batch_status, pre_run_count
        )

    async def _execute_action_run_async(self, params: ActionRunParams) -> ActionExecutionResult:
        """Execute action run (asynchronous)."""
        self._clear_stale_node_disposition(params.action_name)
        self.deps.state_manager.update_status(params.action_name, ActionStatus.RUNNING)
        self._track_action_start(params)
        try:
            correlated_input = self.deps.output_manager.resolve_correlated_input(params.action_idx)
        except AllVersionsFilteredError as avf:
            return self._handle_all_versions_filtered(params, avf)

        # See sync counterpart for the rationale on snapshot placement.
        pre_run_count = self._count_records_for_action(params.action_name)
        try:
            output_folder = await asyncio.to_thread(
                self.deps.action_runner.run_action,
                params.action_config,
                params.action_name,
                None,
                params.action_idx,
                input_directories_override=correlated_input,
            )
        except Exception as e:
            return self._handle_run_failure(params, e)

        duration = (datetime.now() - params.start_time).total_seconds()
        batch_status = self._check_batch_submission(
            params.action_name,
            params.action_idx,
            configured_run_mode=params.action_config.get("run_mode"),
        )
        return self._handle_run_success(
            params, output_folder, duration, batch_status, pre_run_count
        )

    def __repr__(self):
        return f"ActionExecutor(deps={self.deps})"

    def _check_batch_submission(
        self,
        action_name: str,
        action_idx: int,
        configured_run_mode: RunMode | None = None,
    ) -> str | None:
        """Check if batch jobs were submitted."""
        workflow_name = self.deps.action_runner.workflow_name
        agent_io_path = Path(self.deps.action_runner.get_action_folder(workflow_name))
        return cast(
            str | None,
            self.deps.batch_manager.check_batch_submission(
                action_name, action_idx, agent_io_path, configured_run_mode=configured_run_mode
            ),
        )
