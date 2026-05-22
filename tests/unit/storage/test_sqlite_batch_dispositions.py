"""Tests for SQLiteBackend.set_dispositions_batch — single-transaction batch writes."""

from __future__ import annotations

import sqlite3

import pytest

from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    VALID_DISPOSITIONS,
    StorageBackend,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    db_path = tmp_path / "agent_io" / "test.db"
    b = SQLiteBackend(str(db_path), "test_workflow")
    b.initialize()
    yield b
    b.close()


class TestSetDispositionsBatch:
    """Verify batch disposition writes in a single transaction."""

    def test_batch_writes_1000_records(self, backend: SQLiteBackend):
        """1000 records should all be written correctly by a single batch call."""
        batch = [
            ("action_A", f"record_{i}", "success", None, None, None, None) for i in range(1000)
        ]
        backend.set_dispositions_batch(batch)

        rows = backend.get_disposition("action_A")
        assert len(rows) == 1000

    def test_batch_empty_list_is_noop(self, backend: SQLiteBackend):
        """Empty batch should not touch the DB."""
        # Write a record first, then batch-write an empty list.
        backend.set_disposition("action_A", "rec_0", "success")
        backend.set_dispositions_batch([])

        # The pre-existing record should remain untouched.
        rows = backend.get_disposition("action_A")
        assert len(rows) == 1

    def test_batch_validates_all_before_writing(self, backend: SQLiteBackend):
        """Invalid disposition in batch should reject the entire batch — no partial writes."""
        batch = [
            ("action_A", "rec_1", "success", None, None, None, None),
            ("action_A", "rec_2", "INVALID_DISP", None, None, None, None),
            ("action_A", "rec_3", "failed", None, None, None, None),
        ]
        with pytest.raises(ValueError, match="Invalid disposition"):
            backend.set_dispositions_batch(batch)

        # No records should have been written.
        rows = backend.get_disposition("action_A")
        assert len(rows) == 0

    def test_batch_truncates_large_snapshots(self, backend: SQLiteBackend):
        """Snapshots > 10KB should be truncated with __truncated__ marker."""
        large_snapshot = "x" * 20000
        batch = [
            ("action_A", "rec_1", "failed", "error", None, large_snapshot, None),
        ]
        backend.set_dispositions_batch(batch)

        rows = backend.get_disposition("action_A", record_id="rec_1")
        assert len(rows) == 1
        snapshot = rows[0]["input_snapshot"]
        assert '"__truncated__": true' in snapshot
        assert len(snapshot) <= 10240 + 200  # truncated wrapper overhead

    def test_batch_atomicity_on_error(self, backend: SQLiteBackend):
        """If the DB write fails, no partial records should persist.

        We verify atomicity by writing a valid batch first, then attempting
        to write a second batch that will fail due to a constraint violation
        (injecting a NULL into a NOT NULL column by corrupting the table).
        """
        # Write an initial record.
        backend.set_disposition("action_A", "existing", "success")

        # Temporarily break the table to cause an INSERT failure.
        # Add a CHECK constraint that rejects a specific marker value.
        backend.connection.execute(
            "CREATE TRIGGER reject_marker BEFORE INSERT ON record_disposition "
            "BEGIN "
            "  SELECT RAISE(ABORT, 'marker rejected') "
            "  WHERE NEW.record_id = '__FAIL__'; "
            "END"
        )
        backend.connection.commit()

        batch = [
            ("action_A", "rec_ok", "success", None, None, None, None),
            ("action_A", "__FAIL__", "success", None, None, None, None),
        ]
        with pytest.raises(sqlite3.Error):
            backend.set_dispositions_batch(batch)

        # The pre-existing "existing" record should survive; "rec_ok" should NOT persist.
        rows = backend.get_disposition("action_A")
        record_ids = {r["record_id"] for r in rows}
        assert "rec_ok" not in record_ids
        assert "existing" in record_ids

    def test_batch_clears_prior_dispositions(self, backend: SQLiteBackend):
        """Batch write should DELETE prior rows for each (action, record) — no phantom coexistence."""
        # Write FAILED first via single-record method.
        backend.set_disposition("action_A", "rec_1", DISPOSITION_FAILED, reason="error1")

        # Batch write SUCCESS for the same record.
        batch = [("action_A", "rec_1", "success", None, None, None, None)]
        backend.set_dispositions_batch(batch)

        rows = backend.get_disposition("action_A", record_id="rec_1")
        assert len(rows) == 1
        assert rows[0]["disposition"] == "success"

    def test_batch_preserves_all_fields(self, backend: SQLiteBackend):
        """All tuple fields should land in the correct columns."""
        batch = [
            (
                "action_A",
                "rec_1",
                "failed",
                "timeout_error",
                "file.json",
                '{"key": "val"}',
                "detail text",
            ),
        ]
        backend.set_dispositions_batch(batch)

        rows = backend.get_disposition("action_A", record_id="rec_1")
        assert len(rows) == 1
        row = rows[0]
        assert row["disposition"] == "failed"
        assert row["reason"] == "timeout_error"
        assert row["relative_path"] == "file.json"
        assert row["input_snapshot"] == '{"key": "val"}'
        assert row["detail"] == "detail text"

    def test_batch_all_valid_dispositions(self, backend: SQLiteBackend):
        """Every valid disposition value should be accepted in a batch."""
        batch = [
            (f"action_{d}", f"rec_{d}", d, None, None, None, None)
            for d in sorted(VALID_DISPOSITIONS)
        ]
        backend.set_dispositions_batch(batch)

        total = sum(len(backend.get_disposition(f"action_{d}")) for d in sorted(VALID_DISPOSITIONS))
        assert total == len(VALID_DISPOSITIONS)


class TestBaseClassDefault:
    """Verify StorageBackend.set_dispositions_batch default loops over set_disposition."""

    def test_default_delegates_to_set_disposition(self, backend: SQLiteBackend):
        """The base class default should produce the same result as individual calls."""
        # Call via the base class default (explicitly call super's impl).
        batch = [
            ("action_A", "rec_1", "success", None, None, None, None),
            ("action_A", "rec_2", "failed", "err", None, None, None),
        ]
        StorageBackend.set_dispositions_batch(backend, batch)

        rows = backend.get_disposition("action_A")
        assert len(rows) == 2
        disps = {r["record_id"]: r["disposition"] for r in rows}
        assert disps == {"rec_1": "success", "rec_2": "failed"}
