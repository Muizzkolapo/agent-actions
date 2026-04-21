"""Recovery state persistence for async batch retry/reprompt."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.utils.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


_VALID_PHASES = {"retry", "reprompt", "done"}


@dataclass
class RecoveryState:
    """Cross-pass state for batch recovery (retry + reprompt).

    Persisted to disk between workflow re-runs so that the processing
    service can track progress across multiple async batch submissions.
    """

    phase: str  # "retry" | "reprompt" | "done"

    def __post_init__(self):
        if self.phase not in _VALID_PHASES:
            raise ValueError(
                f"Invalid recovery phase '{self.phase}'. "
                f"Expected one of: {', '.join(sorted(_VALID_PHASES))}"
            )

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
    on_exhausted: str = "return_last"

    # Accumulated results (serialized BatchResult dicts)
    accumulated_results: list[dict[str, Any]] = field(default_factory=list)

    # Evaluation loop: graduated results (passed evaluation, never re-evaluated)
    graduated_results: list[dict[str, Any]] = field(default_factory=list)

    # Which evaluation strategy is active (e.g., "validation", "critique")
    evaluation_strategy_name: str | None = None


class RecoveryStateManager:
    """Persists RecoveryState to JSON files in the batch/ subdirectory."""

    @staticmethod
    def save(output_directory: str, file_name: str, state: RecoveryState) -> Path:
        """Save recovery state to disk."""
        state_path = RecoveryStateManager._get_path(output_directory, file_name)
        ensure_directory_exists(state_path, is_file=True)

        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)

        logger.debug(
            "Saved recovery state to %s (phase=%s, retry=%d, reprompt=%d)",
            state_path,
            state.phase,
            state.retry_attempt,
            state.reprompt_attempt,
        )
        return state_path

    @staticmethod
    def load(output_directory: str, file_name: str) -> RecoveryState | None:
        """Load recovery state from disk, or None if not found."""
        state_path = RecoveryStateManager._get_path(output_directory, file_name)
        if not state_path.exists():
            return None

        try:
            with open(state_path, encoding="utf-8") as f:
                data = json.load(f)
            return RecoveryState(**data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to load recovery state from %s: %s", state_path, e)
            return None

    @staticmethod
    def delete(output_directory: str, file_name: str) -> bool:
        """Delete recovery state file. Returns True if deleted, False if not found."""
        state_path = RecoveryStateManager._get_path(output_directory, file_name)
        if state_path.exists():
            state_path.unlink()
            logger.debug("Deleted recovery state at %s", state_path)
            return True
        return False

    @staticmethod
    def exists(output_directory: str, file_name: str) -> bool:
        """Check if recovery state exists."""
        return RecoveryStateManager._get_path(output_directory, file_name).exists()

    @staticmethod
    def _get_path(output_directory: str, file_name: str) -> Path:
        """Get path to recovery state file."""
        if ".." in file_name:
            raise ValueError(f"Invalid file name contains path traversal: {file_name}")
        safe_name = Path(file_name).name
        return Path(output_directory) / "batch" / f".recovery_state_{safe_name}.json"
