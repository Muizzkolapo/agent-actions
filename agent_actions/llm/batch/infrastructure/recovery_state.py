"""Recovery state persistence for async batch retry/reprompt."""

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_actions.llm.batch.core.batch_constants import OnExhaustedPolicy, RecoveryPhase

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class RecoveryState:
    """Cross-pass state for batch recovery (retry + reprompt).

    Persisted to StorageBackend metadata between workflow re-runs so that
    the processing service can track progress across multiple async batch
    submissions.
    """

    phase: RecoveryPhase = RecoveryPhase.RETRY

    def __post_init__(self):
        if isinstance(self.phase, str):
            self.phase = RecoveryPhase(self.phase)
        if isinstance(self.on_exhausted, str):
            self.on_exhausted = OnExhaustedPolicy(self.on_exhausted)

    # Retry state
    retry_attempt: int = 0
    retry_max_attempts: int = 3
    missing_ids: list[str] = field(default_factory=list)
    record_failure_counts: dict[str, int] = field(default_factory=dict)

    # Reprompt state
    reprompt_attempt: int = 0
    reprompt_max_attempts: int = 2
    validation_name: str | None = None
    reprompt_attempts_per_record: dict[str, int] = field(default_factory=dict)
    validation_status: dict[str, bool] = field(default_factory=dict)
    on_exhausted: OnExhaustedPolicy = OnExhaustedPolicy.RETURN_LAST

    # Accumulated results (serialized BatchResult dicts)
    accumulated_results: list[dict[str, Any]] = field(default_factory=list)

    # Evaluation loop: graduated results (passed evaluation, never re-evaluated)
    graduated_results: list[dict[str, Any]] = field(default_factory=list)

    # Which evaluation strategy is active (e.g., "validation", "critique")
    evaluation_strategy_name: str | None = None

    # Per-record failure type counts accumulated across recovery rounds.
    failure_type_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "retry_attempt": self.retry_attempt,
            "retry_max_attempts": self.retry_max_attempts,
            "missing_ids": self.missing_ids,
            "record_failure_counts": self.record_failure_counts,
            "reprompt_attempt": self.reprompt_attempt,
            "reprompt_max_attempts": self.reprompt_max_attempts,
            "validation_name": self.validation_name,
            "reprompt_attempts_per_record": self.reprompt_attempts_per_record,
            "validation_status": self.validation_status,
            "on_exhausted": self.on_exhausted,
            "accumulated_results": self.accumulated_results,
            "graduated_results": self.graduated_results,
            "evaluation_strategy_name": self.evaluation_strategy_name,
            "failure_type_counts": self.failure_type_counts,
        }


class RecoveryStateManager:
    """Persists RecoveryState via StorageBackend metadata store."""

    @staticmethod
    def _metadata_key(action_name: str, file_name: str) -> str:
        if ".." in file_name:
            raise ValueError(f"Invalid file name contains path traversal: {file_name}")
        from pathlib import Path

        safe_name = Path(file_name).name
        return f"recovery_state:{action_name}:{safe_name}"

    @staticmethod
    def save(
        backend: "StorageBackend", action_name: str, file_name: str, state: RecoveryState
    ) -> None:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        backend.save_metadata(key, json.dumps(state.to_dict(), ensure_ascii=False))
        logger.debug(
            "Saved recovery state for %s/%s (phase=%s, retry=%d, reprompt=%d)",
            action_name,
            file_name,
            state.phase,
            state.retry_attempt,
            state.reprompt_attempt,
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
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        if isinstance(backend, SQLiteBackend):
            deleted = backend.delete_metadata(key)
        else:
            backend.save_metadata(key, "")
            deleted = True
        if deleted:
            logger.debug("Deleted recovery state for %s/%s", action_name, file_name)
        return deleted

    @staticmethod
    def exists(backend: "StorageBackend", action_name: str, file_name: str) -> bool:
        key = RecoveryStateManager._metadata_key(action_name, file_name)
        return backend.load_metadata(key) is not None
