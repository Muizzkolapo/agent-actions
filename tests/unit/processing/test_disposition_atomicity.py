"""Regression tests for F14: disposition clear+write must be crash-safe.

The bug: write_record_dispositions() called clear_disposition(DEFERRED)
first, then set_disposition(terminal). A crash between the two left the
record with no disposition at all — invisible.

The fix (Option C): write the terminal disposition BEFORE clearing
DEFERRED. If crash occurs after the terminal write but before the
DEFERRED clear, the record has both rows — but the terminal state is
queryable.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.processing.result_collector import write_record_dispositions
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED


def _make_backend() -> MagicMock:
    backend = MagicMock()
    backend.clear_disposition.return_value = 1
    return backend


def _assert_set_before_clear(backend: MagicMock) -> None:
    """Assert set_disposition was called before clear_disposition."""
    all_calls = backend.method_calls
    set_idx = next(i for i, c in enumerate(all_calls) if c[0] == "set_disposition")
    clear_idx = next(i for i, c in enumerate(all_calls) if c[0] == "clear_disposition")
    assert set_idx < clear_idx, (
        f"set_disposition (idx={set_idx}) must be called before "
        f"clear_disposition (idx={clear_idx}) for crash safety"
    )


class TestDispositionWriteOrder:
    """Terminal disposition must be written BEFORE DEFERRED is cleared."""

    @pytest.mark.parametrize(
        "item",
        [
            pytest.param(
                {"source_guid": "rec-1", "metadata": {}, "error": "timeout"},
                id="failed",
            ),
            pytest.param(
                {"source_guid": "rec-2", "metadata": {"retry_exhausted": True}},
                id="exhausted",
            ),
            pytest.param(
                {
                    "source_guid": "rec-3",
                    "metadata": {"reason": "guard_skip"},
                    "_state": RecordState.GUARD_SKIPPED.value,
                },
                id="guard_skipped",
            ),
            pytest.param(
                {
                    "source_guid": "rec-4",
                    "metadata": {},
                    "_state": RecordState.PROCESSED.value,
                },
                id="success",
            ),
        ],
    )
    def test_terminal_disposition_written_before_deferred_clear(self, item):
        backend = _make_backend()
        write_record_dispositions(backend, [item], "act")
        _assert_set_before_clear(backend)

    def test_crash_after_terminal_write_leaves_queryable_state(self):
        """Simulate crash: clear_disposition raises after terminal is written.
        The terminal disposition must already be committed."""
        backend = _make_backend()
        backend.clear_disposition.side_effect = RuntimeError("simulated crash")
        items = [{"source_guid": "rec-crash", "metadata": {}, "error": "bad input"}]

        write_record_dispositions(backend, items, "act")

        backend.set_disposition.assert_called_once()
        assert backend.set_disposition.call_args[0][2] == DISPOSITION_FAILED

    def test_multiple_records_each_write_terminal_before_clear(self):
        """With multiple non-success records, each record's terminal write
        must precede its own DEFERRED clear."""
        backend = _make_backend()
        items = [
            {"source_guid": "r1", "metadata": {}, "error": "err1"},
            {"source_guid": "r2", "metadata": {"retry_exhausted": True}},
        ]

        write_record_dispositions(backend, items, "act")

        all_calls = backend.method_calls
        for record_id in ("r1", "r2"):
            set_indices = [
                i
                for i, c in enumerate(all_calls)
                if c[0] == "set_disposition" and c[1][1] == record_id
            ]
            clear_indices = [
                i
                for i, c in enumerate(all_calls)
                if c[0] == "clear_disposition" and c[2].get("record_id") == record_id
            ]
            assert len(set_indices) == 1, f"Expected 1 set for {record_id}"
            assert len(clear_indices) == 1, f"Expected 1 clear for {record_id}"
            assert set_indices[0] < clear_indices[0], (
                f"Record {record_id}: set_disposition must precede clear_disposition"
            )

    def test_record_with_no_terminal_only_clears_deferred(self):
        """A record that matches no terminal branch only clears DEFERRED."""
        backend = _make_backend()
        items = [{"source_guid": "rec-none", "metadata": {}}]

        write_record_dispositions(backend, items, "act")

        backend.clear_disposition.assert_called_once_with(
            "act", disposition=DISPOSITION_DEFERRED, record_id="rec-none"
        )
        backend.set_disposition.assert_not_called()
