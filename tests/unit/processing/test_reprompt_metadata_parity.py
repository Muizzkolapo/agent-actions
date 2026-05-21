"""Tests for reprompt metadata parity between online and batch paths.

Spec 417: Reprompt metadata parity (R2 + NEW1 + NEW2).

Ensures batch _recovery.reprompt output matches online shape:
- failure-type counters populated
- validation_name is the actual UDF name
- per-record attempt counts (not global counter)
"""

from unittest.mock import MagicMock

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.exhaustion import apply_exhausted_reprompt
from agent_actions.processing.evaluation.strategies.validation import ValidationStrategy
from agent_actions.processing.types import RepromptMetadata


def _make_result(custom_id, success=True, content=None, recovery_metadata=None):
    r = MagicMock(spec=BatchResult)
    r.custom_id = custom_id
    r.success = success
    r.content = content
    r.error = None if success else "API error"
    r.recovery_metadata = recovery_metadata
    return r


# ---------------------------------------------------------------------------
# Bug 1: failure-type counters
# ---------------------------------------------------------------------------


class TestFailureTypeCounters:
    def test_exhaustion_populates_parse_error_count(self):
        """parse_error_count populated from failure_type_counts."""
        results = [_make_result("r1")]
        ftc = {"r1": {"parse_error": 2, "udf_fail": 0}}

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1"},
            validation_name="check_output",
            attempt=3,
            on_exhausted="return_last",
            failure_type_counts=ftc,
        )

        meta = results[0].recovery_metadata.reprompt
        assert meta.parse_error_count == 2
        assert meta.udf_fail_count == 0
        assert meta.schema_fail_count == 0

    def test_exhaustion_populates_udf_fail_count(self):
        """udf_fail_count populated from failure_type_counts."""
        results = [_make_result("r1")]
        ftc = {"r1": {"udf_fail": 3}}

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1"},
            validation_name="check_output",
            attempt=3,
            on_exhausted="return_last",
            failure_type_counts=ftc,
        )

        assert results[0].recovery_metadata.reprompt.udf_fail_count == 3

    def test_mixed_failure_types_per_record(self):
        """Each record gets its own failure type counts."""
        results = [_make_result("r1"), _make_result("r2")]
        ftc = {
            "r1": {"parse_error": 1, "udf_fail": 1},
            "r2": {"udf_fail": 2},
        }

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1", "r2"},
            validation_name="check",
            attempt=3,
            on_exhausted="return_last",
            failure_type_counts=ftc,
        )

        r1_meta = results[0].recovery_metadata.reprompt
        r2_meta = results[1].recovery_metadata.reprompt
        assert r1_meta.parse_error_count == 1
        assert r1_meta.udf_fail_count == 1
        assert r2_meta.parse_error_count == 0
        assert r2_meta.udf_fail_count == 2

    def test_counters_present_in_to_dict_when_nonzero(self):
        """RepromptMetadata.to_dict() includes counter keys when non-zero."""
        meta = RepromptMetadata(
            attempts=3,
            passed=False,
            validation="check_output",
            parse_error_count=1,
            udf_fail_count=2,
        )
        d = meta.to_dict()

        assert "parse_error_count" in d
        assert d["parse_error_count"] == 1
        assert "udf_fail_count" in d
        assert d["udf_fail_count"] == 2
        assert "schema_fail_count" not in d  # 0, so omitted

    def test_no_failure_type_counts_defaults_to_zero(self):
        """Without failure_type_counts, all counters default to 0."""
        results = [_make_result("r1")]

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1"},
            validation_name="check",
            attempt=2,
            on_exhausted="return_last",
        )

        meta = results[0].recovery_metadata.reprompt
        assert meta.parse_error_count == 0
        assert meta.udf_fail_count == 0
        assert meta.schema_fail_count == 0


# ---------------------------------------------------------------------------
# Bug 2: validation_name
# ---------------------------------------------------------------------------


class TestValidationName:
    def test_strategy_name_is_actual_udf_name(self):
        """ValidationStrategy.name returns the configured UDF name, not 'validation'."""
        strategy = ValidationStrategy(
            validation_func=lambda r: True,
            feedback_message="fix",
            validation_name="check_output_quality",
        )
        assert strategy.name == "check_output_quality"

    def test_strategy_name_defaults_to_validation(self):
        """Without explicit name, falls back to 'validation' for backward compat."""
        strategy = ValidationStrategy(
            validation_func=lambda r: True,
            feedback_message="fix",
        )
        assert strategy.name == "validation"

    def test_exhaustion_metadata_uses_actual_validation_name(self):
        """apply_exhausted_reprompt writes the actual validation name."""
        results = [_make_result("r1")]

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1"},
            validation_name="check_output_quality",
            attempt=3,
            on_exhausted="return_last",
        )

        assert results[0].recovery_metadata.reprompt.validation == "check_output_quality"


# ---------------------------------------------------------------------------
# Bug 3: per-record attempt counts
# ---------------------------------------------------------------------------


class TestPerRecordAttempts:
    def test_per_record_attempts_used_over_global(self):
        """Per-record attempt counts override the global attempt counter."""
        results = [_make_result("r1"), _make_result("r2")]
        per_record = {"r1": 1, "r2": 3}

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1", "r2"},
            validation_name="check",
            attempt=5,  # global counter — should NOT be used
            on_exhausted="return_last",
            per_record_attempts=per_record,
        )

        assert results[0].recovery_metadata.reprompt.attempts == 1
        assert results[1].recovery_metadata.reprompt.attempts == 3

    def test_global_attempt_used_when_per_record_missing(self):
        """Falls back to global attempt when per_record_attempts not provided."""
        results = [_make_result("r1")]

        apply_exhausted_reprompt(
            results=results,
            failed_ids={"r1"},
            validation_name="check",
            attempt=2,
            on_exhausted="return_last",
        )

        assert results[0].recovery_metadata.reprompt.attempts == 2


# ---------------------------------------------------------------------------
# RecoveryState serialization of failure_type_counts
# ---------------------------------------------------------------------------


class TestRecoveryStateFailureTypeCounts:
    def test_failure_type_counts_serialized(self):
        """failure_type_counts round-trips through to_dict / from_dict."""
        from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState

        state = RecoveryState(phase="reprompt")
        state.failure_type_counts = {"r1": {"parse_error": 1, "udf_fail": 2}}

        d = state.to_dict()
        assert d["failure_type_counts"] == {"r1": {"parse_error": 1, "udf_fail": 2}}

        restored = RecoveryState(**d)
        assert restored.failure_type_counts == {"r1": {"parse_error": 1, "udf_fail": 2}}
