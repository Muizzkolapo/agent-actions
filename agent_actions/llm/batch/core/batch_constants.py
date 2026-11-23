"""Constants for batch processing: status enums and metadata keys."""

from enum import Enum

from agent_actions.errors.classification import mark_action_fatal


class BatchStatus(str, Enum):
    """Batch job status values (inherits str for JSON serialization)."""

    SUBMITTED = "submitted"
    VALIDATING = "validating"
    IN_PROGRESS = "in_progress"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def terminal_states(cls) -> set["BatchStatus"]:
        """Return the set of terminal (final) batch states."""
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED}

    @classmethod
    def in_flight_states(cls) -> set["BatchStatus"]:
        """Return the set of in-flight (active) batch states."""
        return {cls.SUBMITTED, cls.VALIDATING, cls.IN_PROGRESS, cls.FINALIZING}

    def is_terminal(self) -> bool:
        """Check if this status is a terminal state."""
        return self in self.terminal_states()

    def is_in_flight(self) -> bool:
        """Check if this status is an in-flight state."""
        return self in self.in_flight_states()


class FilterStatus(str, Enum):
    """Record filter status during batch task preparation."""

    INCLUDED = "included"
    SKIPPED = "skipped"
    FILTERED = "filtered"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


class RecoveryType(str, Enum):
    """Type of recovery operation for async batch processing."""

    RETRY = "retry"
    REPAIR = "repair"
    # The side calls of a step over a returned batch, sent as a batch of their own;
    # the registry entry names their kind (``side_kind``).
    SIDE = "side"

    def __str__(self) -> str:
        return self.value


class RecoveryPhase(str, Enum):
    """Current phase in the recovery state machine."""

    RETRY = "retry"
    REPAIR = "repair"
    DONE = "done"

    def __str__(self) -> str:
        return self.value


class UnknownRecoveryState(RuntimeError):
    """Stored state names a recovery type or phase this version does not know."""


def _refuse_unknown(kind: str, value: str, known: type[Enum]) -> None:
    # Not a ValueError: the loaders skip those, and a skipped entry makes its
    # parent batch look unsubmitted, so the next run pays for it again.
    if value not in {member.value for member in known}:
        # Its remedy, --fresh, is the action's, not one file's.
        raise mark_action_fatal(
            UnknownRecoveryState(
                f"The stored recovery {kind} '{value}' is not one this version knows. "
                f"Its stored state cannot be resumed. Re-run the action with --fresh to "
                f"start it again; the records it had already completed are in the store."
            )
        )


def coerce_recovery_phase(value: str) -> RecoveryPhase:
    _refuse_unknown("phase", value, RecoveryPhase)
    return RecoveryPhase(value)


def coerce_recovery_type(value: str) -> RecoveryType:
    _refuse_unknown("type", value, RecoveryType)
    return RecoveryType(value)


class OnExhaustedPolicy(str, Enum):
    """Policy when retry or repair attempts are exhausted."""

    RETURN_LAST = "return_last"
    RAISE = "raise"

    def __str__(self) -> str:
        """Return the string value for str() conversion."""
        return self.value


class ContextMetaKeys:
    """Internal underscore-prefixed metadata keys used in batch context maps."""

    FILTER_STATUS = "_batch_filter_status"
    FILTER_PHASE = "_batch_filter_phase"  # "phase1" or "phase2" - which phase filtered
    PASSTHROUGH_FIELDS = "_passthrough_fields"
    SKIP_REASON = "_batch_skip_reason"
    PREP_ERROR = "_batch_prep_error"
    # The schema a ``schema: dispatch_task(...)`` chose for the row; a repair round reads it.
    OUTPUT_SCHEMA = "_batch_output_schema"
    # The LLM context values the action's ``llm_judge`` rules reference, for the verdict
    # passes that run once the answers are back.
    JUDGE_CONTEXT = "_batch_judge_context"

    @classmethod
    def all_internal_keys(cls) -> set[str]:
        """Return set of all internal metadata key names."""
        return {
            cls.FILTER_STATUS,
            cls.FILTER_PHASE,
            cls.PASSTHROUGH_FIELDS,
            cls.SKIP_REASON,
            cls.PREP_ERROR,
            cls.OUTPUT_SCHEMA,
            cls.JUDGE_CONTEXT,
        }
