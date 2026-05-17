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


class TestContextMapIntegrity:
    """U-2.B: context_map must not show INCLUDED for records where prepare() failed."""

    @pytest.fixture()
    def prep_harness(self, batch_preparator):
        """Shared setup for _process_single_item tests."""
        return {
            "preparator": batch_preparator,
            "context_map": {},
            "stats": BatchTaskPreparationStats(),
            "prep_context": MagicMock(spec=PreparationContext),
        }

    def _run(self, prep_harness, row, task_preparer):
        """Run _process_single_item with the shared harness."""
        return prep_harness["preparator"]._process_single_item(
            row,
            prep_harness["prep_context"],
            task_preparer,
            prep_harness["context_map"],
            prep_harness["stats"],
        )

    def test_prepare_failure_not_marked_included(self, prep_harness):
        """If prepare() throws, context_map must NOT have INCLUDED for that row.

        Bug: INCLUDED is set before prepare() runs, so when prepare() throws,
        the exception propagates out of _process_single_item and the
        context_map entry is left with INCLUDED — a lie.
        """
        row = {"target_id": "t-001", "content": {"text": "will fail"}}
        task_preparer = MagicMock()
        task_preparer.prepare.side_effect = ValueError("schema validation failed")

        with pytest.raises(ValueError, match="schema validation failed"):
            self._run(prep_harness, row, task_preparer)

        context_map = prep_harness["context_map"]
        assert "t-001" in context_map

        status = BatchContextMetadata.get_filter_status(context_map["t-001"])
        assert status != FilterStatus.INCLUDED, (
            f"context_map shows INCLUDED for row where prepare() failed — "
            f"INCLUDED was set before prepare() ran (got status={status})"
        )

    def test_successful_prepare_marked_included(self, prep_harness):
        """When prepare() succeeds and guard passes, context_map shows INCLUDED."""
        row = {"target_id": "t-002", "content": {"text": "will succeed"}}
        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.PASSED
        prepared.passthrough_fields = {}
        prepared.llm_context = {"text": "prepared"}
        prepared.formatted_prompt = "Process this"
        task_preparer.prepare.return_value = prepared

        result = self._run(prep_harness, row, task_preparer)

        assert result is not None
        status = BatchContextMetadata.get_filter_status(prep_harness["context_map"]["t-002"])
        assert status == FilterStatus.INCLUDED, (
            f"context_map must show INCLUDED after successful prepare (got status={status})"
        )
        stats = prep_harness["stats"]
        assert stats.included_items == 0, (
            "included_items is counted by caller, not _process_single_item"
        )

    def test_guard_skipped_not_marked_included(self, prep_harness):
        """When guard skips a record, context_map shows SKIPPED, not INCLUDED."""
        row = {"target_id": "t-003", "content": {"text": "guard skip"}}
        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.SKIPPED
        prepared.passthrough_fields = {}
        task_preparer.prepare.return_value = prepared

        result = self._run(prep_harness, row, task_preparer)

        assert result is None
        status = BatchContextMetadata.get_filter_status(prep_harness["context_map"]["t-003"])
        assert status == FilterStatus.SKIPPED
        assert prep_harness["stats"].skipped_items == 1

    def test_guard_filtered_marked_filtered(self, prep_harness):
        """When guard filters a record, context_map shows FILTERED, not INCLUDED."""
        row = {"target_id": "t-004", "content": {"text": "guard filter"}}
        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.FILTERED
        prepared.passthrough_fields = {}
        task_preparer.prepare.return_value = prepared

        result = self._run(prep_harness, row, task_preparer)

        assert result is None
        status = BatchContextMetadata.get_filter_status(prep_harness["context_map"]["t-004"])
        assert status == FilterStatus.FILTERED
        assert prep_harness["stats"].filtered_items == 1

    def test_upstream_unprocessed_marked_skipped(self, prep_harness):
        """When upstream is unprocessed, context_map shows SKIPPED with reason."""
        row = {"target_id": "t-005", "content": {"text": "upstream unprocessed"}}
        task_preparer = MagicMock()
        prepared = MagicMock()
        prepared.guard_status = GuardStatus.UPSTREAM_UNPROCESSED
        prepared.passthrough_fields = {}
        task_preparer.prepare.return_value = prepared

        result = self._run(prep_harness, row, task_preparer)

        assert result is None
        entry = prep_harness["context_map"]["t-005"]
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.SKIPPED
        assert BatchContextMetadata.get_skip_reason(entry) == "upstream_unprocessed"
        assert prep_harness["stats"].skipped_items == 1


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
        assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED
        assert entry["_state"] == RecordState.FAILED.value

        # transition() writes structured history — assert on content, not just existence
        history = entry.get("_state_history")
        assert isinstance(history, list) and len(history) > 0, (
            "_mark_prep_failed must use transition() which writes _state_history entries"
        )
        last = history[-1]
        assert last["to"] == RecordState.FAILED.value
        assert last["action"] == "test_agent"
        assert "test error" in last["reason"]

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
