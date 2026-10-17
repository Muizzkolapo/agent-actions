"""Recovery state persistence for async batch retry and repair."""

import json
import logging
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import (
    OnExhaustedPolicy,
    RecoveryPhase,
    RecoveryType,
    coerce_recovery_phase,
)
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    checked_batch_file_name,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def retries_left(retries_sent: int, max_attempts: int) -> int:
    """Retry batches still allowed once the original batch and *retries_sent* retries went out.

    ``retry.max_attempts`` counts every attempt, the original included, as online does.
    """
    return max_attempts - 1 - retries_sent


@dataclass
class RecoveryState:
    """Cross-pass state for batch recovery (retry + repair).

    Persisted to StorageBackend metadata between workflow re-runs so that
    the processing service can track progress across multiple async batch
    submissions.
    """

    phase: RecoveryPhase = RecoveryPhase.RETRY

    def __post_init__(self):
        if isinstance(self.phase, str):
            self.phase = coerce_recovery_phase(self.phase)
        if isinstance(self.on_exhausted, str):
            self.on_exhausted = OnExhaustedPolicy(self.on_exhausted)

    # Retry state
    retry_attempt: int = 0
    retry_max_attempts: int = 3
    missing_ids: list[str] = field(default_factory=list)
    record_failure_counts: dict[str, int] = field(default_factory=dict)

    on_exhausted: OnExhaustedPolicy = OnExhaustedPolicy.RETURN_LAST

    # Repair state (expect: regeneration rounds)
    repair_attempt: int = 0
    repair_submitted_ids: list[str] = field(default_factory=list)
    repair_judge_budget_remaining: int | None = None
    repair_max_attempts: int = 1

    # Accumulated results (serialized BatchResult dicts)
    accumulated_results: list[dict[str, Any]] = field(default_factory=list)

    # Evaluation loop: graduated results (passed evaluation, never re-evaluated)
    graduated_results: list[dict[str, Any]] = field(default_factory=list)

    # Which evaluation strategy is active (e.g., "validation", "critique")
    evaluation_strategy_name: str | None = None

    # Per-record failure type counts accumulated across recovery rounds.
    failure_type_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Every declared field, so adding one cannot silently stop persisting it.

        A dropped field does not fail loudly: the deferred loop reads it back as
        the dataclass default on the next pass and never advances. Only
        init fields, since load() reconstructs via ``RecoveryState(**data)`` and
        an unexpected keyword there raises a TypeError that load swallows —
        wiping the whole state rather than reporting it.
        """
        return {f.name: getattr(self, f.name) for f in fields(self) if f.init}


class RecoveryStateManager:
    """Persists RecoveryState via StorageBackend metadata store."""

    @staticmethod
    def _metadata_key(action_name: str, file_name: str) -> str:
        return f"recovery_state:{action_name}:{checked_batch_file_name(file_name)}"

    @staticmethod
    def save(
        backend: "StorageBackend", action_name: str, file_name: str, state: RecoveryState
    ) -> None:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        backend.save_metadata(key, json.dumps(state.to_dict(), ensure_ascii=False))
        logger.debug(
            "Saved recovery state for %s/%s (phase=%s, retry=%d, repair=%d)",
            action_name,
            file_name,
            state.phase,
            state.retry_attempt,
            state.repair_attempt,
        )

    @staticmethod
    def load(backend: "StorageBackend", action_name: str, file_name: str) -> RecoveryState | None:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        raw = backend.load_metadata(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return RecoveryState(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error("Corrupt recovery state for %s/%s: %s", action_name, file_name, e)
            return None

    @staticmethod
    def delete(backend: "StorageBackend", action_name: str, file_name: str) -> bool:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        deleted = backend.delete_metadata(key)
        if deleted:
            logger.debug("Deleted recovery state for %s/%s", action_name, file_name)
        return deleted

    @staticmethod
    def exists(backend: "StorageBackend", action_name: str, file_name: str) -> bool:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        return backend.load_metadata(key) is not None


@dataclass(frozen=True)
class AwaitingRecovery:
    """The recovery round a DEFERRED record waits on, and the failure that sent it there.

    ``failure`` is the error recorded for the record's last attempt; None when the
    provider returned nothing for it, and always None for a repair round.
    """

    recovery_type: RecoveryType
    attempt: int
    max_attempts: int
    failure: str | None


def records_awaiting_recovery(
    backend: "StorageBackend", action_name: str
) -> dict[str, AwaitingRecovery]:
    """Each source_guid a recovery batch not yet collected holds, and where it waits.

    Read from what a collect pass leaves once it submits a recovery batch: the registry
    entry, the parent file's recovery state and its context map. A file whose state or
    map cannot be read contributes nothing, so its records stay unexplained.
    """
    parents = {
        entry.parent_file_name: RecoveryType(entry.recovery_type)
        for entry in BatchRegistryManager(backend, action_name).get_all_jobs().values()
        if entry.recovery_type is not None and entry.parent_file_name and not entry.collected_at
    }

    awaiting: dict[str, AwaitingRecovery] = {}
    for parent, recovery_type in parents.items():
        try:
            state = RecoveryStateManager.load(backend, action_name, parent)
            if state is None:
                continue
            context_map = BatchContextManager.load_batch_context_map(backend, action_name, parent)
        except Exception:
            logger.debug("Could not read the recovery of %s/%s", action_name, parent, exc_info=True)
            continue

        failures: dict[str, str] = {}
        if recovery_type == RecoveryType.RETRY:
            held = state.missing_ids
            attempt, max_attempts = state.retry_attempt + 1, state.retry_max_attempts
            failures = {
                str(r.get("custom_id")): str(r["error"])
                for r in state.accumulated_results
                if isinstance(r, dict) and r.get("error")
            }
        else:
            held = state.repair_submitted_ids
            attempt, max_attempts = state.repair_attempt, state.repair_max_attempts

        for custom_id in held:
            record = context_map.get(custom_id)
            guid = record.get("source_guid") if isinstance(record, dict) else None
            if guid:
                awaiting[str(guid)] = AwaitingRecovery(
                    recovery_type, attempt, max_attempts, failures.get(custom_id)
                )
    return awaiting
