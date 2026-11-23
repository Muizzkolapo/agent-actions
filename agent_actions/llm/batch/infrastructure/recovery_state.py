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

    # Side rounds: a step's side calls sent as a batch of their own, one kind a round.
    # The rounds sent so far, by kind.
    side_attempts: dict[str, int] = field(default_factory=dict)
    # The kind of the side batch out now, and each of its requests to the key of the
    # call it is a copy of.
    side_kind: str | None = None
    side_requests: dict[str, str] = field(default_factory=dict)
    # The model that batch's calls name; None is the action's own.
    side_model: str | None = None
    # What the side batches returned, as each kind's requester settled it: kind, then
    # call key, to its result.
    side_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    # The results waiting on the side batch, and the step that reads them: "evaluate"
    # (check_and_submit_repair) or "repair" (handle_repair_recovery).
    side_waiting: list[dict[str, Any]] = field(default_factory=list)
    side_resumes: str | None = None

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
    # The kind of side call a side batch answers; None for a retry or repair round.
    side_kind: str | None = None
    # The batch does not hold the record: its file, written whole, waits on that batch.
    for_its_file: bool = False


def records_awaiting_recovery(
    backend: "StorageBackend", action_name: str
) -> dict[str, AwaitingRecovery]:
    """Each source_guid a recovery batch not yet collected holds or waits for, and where.

    Read from what a collect pass leaves once it submits a recovery batch: the registry
    entry, the parent file's recovery state and its context map. The other records of
    that file wait for it (``for_its_file``). A file whose state or map cannot be read
    contributes nothing, so its records stay unexplained.
    """
    parents = {
        entry.parent_file_name: (RecoveryType(entry.recovery_type), entry.side_kind)
        for entry in BatchRegistryManager(backend, action_name).get_all_jobs().values()
        if entry.recovery_type is not None and entry.parent_file_name and not entry.collected_at
    }

    awaiting: dict[str, AwaitingRecovery] = {}
    file_mates: dict[str, AwaitingRecovery] = {}
    for parent, (recovery_type, side_kind) in parents.items():
        try:
            state = RecoveryStateManager.load(backend, action_name, parent)
            if state is None:
                continue
            context_map = BatchContextManager.load_batch_context_map(backend, action_name, parent)
        except Exception:
            logger.debug(
                "Could not read the recovery of %s/%s", action_name, parent, exc_info=True
            )
            continue

        failures: dict[str, str] = {}
        if recovery_type == RecoveryType.SIDE:
            held = [str(r.get("custom_id")) for r in state.side_waiting if isinstance(r, dict)]
            attempt = max_attempts = state.side_attempts.get(side_kind or "", 0)
        elif recovery_type == RecoveryType.RETRY:
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
                    recovery_type, attempt, max_attempts, failures.get(custom_id), side_kind
                )
        held_ids = set(held)
        for custom_id, record in context_map.items():
            guid = record.get("source_guid") if isinstance(record, dict) else None
            if guid and custom_id not in held_ids:
                file_mates[str(guid)] = AwaitingRecovery(
                    recovery_type, attempt, max_attempts, None, side_kind, for_its_file=True
                )
    for guid, where in file_mates.items():
        awaiting.setdefault(guid, where)
    return awaiting
