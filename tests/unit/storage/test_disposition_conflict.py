"""Tests for P0-5: Clear conflicting dispositions before writing terminal.

The disposition table's UNIQUE constraint is (action_name, record_id, disposition),
not (action_name, record_id). Without the DELETE-before-INSERT fix, writing SUCCESS
for a record that previously had FAILED results in BOTH rows coexisting — phantom
failures that _resolve_completion_status would report.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    """Create a fresh SQLiteBackend for each test."""
    db_path = tmp_path / "test.db"
    b = SQLiteBackend(str(db_path), workflow_name="test_workflow")
    b.initialize()
    return b


class TestDispositionConflictClearing:
    """Verify that set_disposition clears prior conflicting dispositions."""

    @pytest.mark.parametrize(
        ("writes", "record_id", "expected"),
        [
            pytest.param(
                [("failed", "llm error"), ("success", None)],
                "rec1",
                "success",
                id="success-replaces-failed",
            ),
            pytest.param(
                [("success", None), ("failed", "retry failed")],
                "rec1",
                "failed",
                id="failed-replaces-success",
            ),
            pytest.param(
                [("failed", "first"), ("skipped", "second"), ("success", None)],
                "rec1",
                "success",
                id="terminal-replaces-any-prior",
            ),
            pytest.param(
                [("failed", "node fail"), ("success", None)],
                "__node__",
                "success",
                id="node-level-sentinel",
            ),
        ],
    )
    def test_last_write_leaves_the_only_row(self, backend, writes, record_id, expected):
        """The last disposition written clears every prior one for that record."""
        for disposition, reason in writes:
            backend.set_disposition("action_A", record_id, disposition, reason=reason)

        rows = backend.connection.execute(
            "SELECT disposition FROM record_disposition "
            "WHERE action_name = 'action_A' AND record_id = ?",
            (record_id,),
        ).fetchall()

        assert len(rows) == 1
        assert rows[0][0] == expected

    def test_no_phantom_failures_in_get_failed_items(self, backend):
        """After SUCCESS overwrites FAILED, get_failed_items returns empty."""
        backend.set_disposition("action_A", "rec1", "failed", reason="timeout")
        backend.set_disposition("action_A", "rec1", "success")

        failed = backend.get_failed_items("action_A")
        assert failed == []

    def test_different_records_unaffected(self, backend):
        """Clearing for rec1 does not affect rec2 at the same action."""
        backend.set_disposition("action_A", "rec1", "failed", reason="err")
        backend.set_disposition("action_A", "rec2", "failed", reason="err")
        backend.set_disposition("action_A", "rec1", "success")

        rec1_rows = backend.connection.execute(
            "SELECT disposition FROM record_disposition "
            "WHERE action_name = 'action_A' AND record_id = 'rec1'"
        ).fetchall()
        rec2_rows = backend.connection.execute(
            "SELECT disposition FROM record_disposition "
            "WHERE action_name = 'action_A' AND record_id = 'rec2'"
        ).fetchall()

        assert len(rec1_rows) == 1
        assert rec1_rows[0][0] == "success"
        assert len(rec2_rows) == 1
        assert rec2_rows[0][0] == "failed"

    def test_different_actions_unaffected(self, backend):
        """Clearing for action_A does not affect action_B for the same record."""
        backend.set_disposition("action_A", "rec1", "failed", reason="err")
        backend.set_disposition("action_B", "rec1", "failed", reason="err")
        backend.set_disposition("action_A", "rec1", "success")

        action_a = backend.connection.execute(
            "SELECT disposition FROM record_disposition "
            "WHERE action_name = 'action_A' AND record_id = 'rec1'"
        ).fetchall()
        action_b = backend.connection.execute(
            "SELECT disposition FROM record_disposition "
            "WHERE action_name = 'action_B' AND record_id = 'rec1'"
        ).fetchall()

        assert len(action_a) == 1
        assert action_a[0][0] == "success"
        assert len(action_b) == 1
        assert action_b[0][0] == "failed"

    def test_reason_and_detail_preserved_on_overwrite(self, backend):
        """The new disposition's reason and detail are preserved after clearing."""
        backend.set_disposition("action_A", "rec1", "failed", reason="old reason")
        backend.set_disposition(
            "action_A", "rec1", "success", reason="new reason", detail="detail info"
        )

        row = backend.connection.execute(
            "SELECT disposition, reason, detail FROM record_disposition "
            "WHERE action_name = 'action_A' AND record_id = 'rec1'"
        ).fetchone()

        assert row[0] == "success"
        assert row[1] == "new reason"
        assert row[2] == "detail info"
