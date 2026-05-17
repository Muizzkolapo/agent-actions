"""Phase 2 batch prep integrity tests — U-2.B, U-1.3a, U-2.C.

Tests that:
- context_map does not show INCLUDED for rows where prepare() failed (U-2.B)
- _mark_prep_failed uses transition() API, not raw _state writes (U-1.3a)
- No RecordEnvelopeError catch-and-bypass pattern (U-2.C)

U-2.B test MUST FAIL against current code (bug exists).
U-1.3a and U-2.C tests confirm Phase 1 fixes hold (regression).
"""

import logging
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchTaskPreparationStats
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.record.state import RecordState

_PREPARATOR_LOGGER = "agent_actions.llm.batch.processing.preparator"


@pytest.fixture(autouse=True)
def _enable_log_propagation():
    """Ensure agent_actions loggers propagate to root so caplog captures them."""
    aa_logger = logging.getLogger("agent_actions")
    orig = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = orig


class TestContextMapIntegrity:
    """U-2.B: context_map must not show INCLUDED for records where prepare() failed."""

    def test_prepare_failure_not_marked_included(self, batch_preparator):
        """If prepare() throws, context_map must NOT have INCLUDED for that row.

        Bug: INCLUDED is set before prepare() runs, so when prepare() throws,
        the exception propagates out of _process_single_item and the
        context_map entry is left with INCLUDED — a lie.
        """
        row = {"target_id": "t-001", "content": {"text": "will fail"}}
        context_map: dict = {}
        stats = BatchTaskPreparationStats()
        prep_context = MagicMock(spec=PreparationContext)

        task_preparer = MagicMock()
        task_preparer.prepare.side_effect = ValueError("schema validation failed")

        with pytest.raises(ValueError, match="schema validation failed"):
            batch_preparator._process_single_item(
                row, prep_context, task_preparer, context_map, stats
            )

        # Row must be in context_map (for _mark_prep_failed to find it later)
        assert "t-001" in context_map

        # But it must NOT be marked INCLUDED — prepare() never succeeded
        status = BatchContextMetadata.get_filter_status(context_map["t-001"])
        assert status != FilterStatus.INCLUDED, (
            f"context_map shows INCLUDED for row where prepare() failed — "
            f"INCLUDED was set before prepare() ran (got status={status})"
        )

    def test_successful_prepare_marked_included(self, batch_preparator):
        """When prepare() succeeds and guard passes, context_map shows INCLUDED."""
        row = {"target_id": "t-002", "content": {"text": "will succeed"}}
        context_map: dict = {}
        stats = BatchTaskPreparationStats()
        prep_context = MagicMock(spec=PreparationContext)

        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.PASSED
        prepared.passthrough_fields = {}
        prepared.llm_context = {"text": "prepared"}
        prepared.formatted_prompt = "Process this"
        task_preparer.prepare.return_value = prepared

        result = batch_preparator._process_single_item(
            row, prep_context, task_preparer, context_map, stats
        )

        assert result is not None
        status = BatchContextMetadata.get_filter_status(context_map["t-002"])
        assert status == FilterStatus.INCLUDED, (
            f"context_map must show INCLUDED after successful prepare (got status={status})"
        )

    def test_guard_skipped_not_marked_included(self, batch_preparator):
        """When guard skips a record, context_map shows SKIPPED, not INCLUDED."""
        row = {"target_id": "t-003", "content": {"text": "guard skip"}}
        context_map: dict = {}
        stats = BatchTaskPreparationStats()
        prep_context = MagicMock(spec=PreparationContext)

        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.SKIPPED
        prepared.passthrough_fields = {}
        task_preparer.prepare.return_value = prepared

        result = batch_preparator._process_single_item(
            row, prep_context, task_preparer, context_map, stats
        )

        assert result is None
        status = BatchContextMetadata.get_filter_status(context_map["t-003"])
        assert status == FilterStatus.SKIPPED


class TestEnvelopeTransitionIntegrity:
    """U-1.3a + U-2.C: _mark_prep_failed uses transition() API, no raw _state bypass.

    These tests confirm Phase 1 fixes hold as regression coverage.
    """

    def test_mark_prep_failed_uses_transition_api(self, batch_preparator, caplog):
        """_mark_prep_failed must call RecordEnvelope.transition(), not raw _state write."""
        record = {"target_id": "t-001", "content": {"text": "will fail"}}
        context_map = {"t-001": record.copy()}

        with caplog.at_level(logging.DEBUG, logger=_PREPARATOR_LOGGER):
            batch_preparator._mark_prep_failed(
                record, context_map, "test_agent", ValueError("test error")
            )

        entry = context_map["t-001"]
        # FilterStatus must be FAILED
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED

        # _state must be set via transition() — evidenced by _state_history existing
        assert "_state_history" in entry, (
            "_mark_prep_failed must use transition() which sets _state_history"
        )
        assert entry["_state"] == RecordState.FAILED.value

    def test_illegal_transition_logs_warning_no_raw_write(self, batch_preparator, caplog):
        """If transition is illegal, must log WARNING and NOT do raw _state write."""
        record = {"target_id": "t-001", "content": {"text": "test"}}
        # Put record in a state that cannot transition to FAILED
        context_map = {"t-001": record.copy()}
        # Force an illegal state value
        context_map["t-001"]["_state"] = "NONEXISTENT_STATE"

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            batch_preparator._mark_prep_failed(
                record, context_map, "test_agent", ValueError("test error")
            )

        entry = context_map["t-001"]
        # FilterStatus should still be FAILED (context_map metadata is separate from _state)
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED

        # _state must NOT have been changed via raw write — it should still be the bad value
        assert entry["_state"] == "NONEXISTENT_STATE", (
            "Raw _state must not be overwritten when transition is illegal"
        )

        # Must log a warning about the failed transition
        warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "Cannot transition" in r.message
        ]
        assert len(warnings) > 0, "Must log WARNING when transition to FAILED is illegal"
