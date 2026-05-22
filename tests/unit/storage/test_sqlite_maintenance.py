"""Tests for SQLite storage backend maintenance operations (P4-2)."""

from datetime import datetime, timedelta

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture()
def backend(tmp_path):
    """Create and initialize a SQLiteBackend for testing."""
    db_path = str(tmp_path / "test.db")
    b = SQLiteBackend(db_path, "test_workflow")
    b.initialize()
    return b


class TestWalCheckpoint:
    """Tests for WAL checkpoint after workflow completion."""

    def test_checkpoint_succeeds_on_clean_db(self, backend):
        """WAL checkpoint runs without error on a clean database."""
        backend._checkpoint_wal()

    def test_checkpoint_after_writes(self, backend):
        """WAL checkpoint runs after data has been written."""
        backend.write_source("file1.json", [{"source_guid": "g1", "data": "test"}])
        backend._checkpoint_wal()

    def test_checkpoint_is_idempotent(self, backend):
        """Multiple WAL checkpoints in sequence are safe."""
        backend._checkpoint_wal()
        backend._checkpoint_wal()


class TestDispositionCleanup:
    """Tests for stale disposition cleanup on successful re-run."""

    def _insert_disposition(self, backend, action, record_id, disposition, reason=None):
        """Insert a disposition row directly (bypassing DELETE-before-INSERT)."""
        with backend._lock:
            backend.connection.execute(
                """
                INSERT INTO record_disposition
                (action_name, record_id, disposition, reason, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (action, record_id, disposition, reason),
            )
            backend.connection.commit()

    def test_removes_old_failed_when_success_exists(self, backend):
        """Old FAILED disposition removed when newer SUCCESS exists for same record."""
        # Insert directly to simulate dispositions accumulated across runs
        self._insert_disposition(backend, "action_a", "record_1", "failed", "error")
        self._insert_disposition(backend, "action_a", "record_1", "success")

        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        dispositions = [r["disposition"] for r in rows]
        assert "success" in dispositions
        assert "failed" not in dispositions

    def test_removes_old_exhausted_when_success_exists(self, backend):
        """Old EXHAUSTED disposition removed when newer SUCCESS exists."""
        self._insert_disposition(backend, "action_a", "record_1", "exhausted", "retries")
        self._insert_disposition(backend, "action_a", "record_1", "success")

        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        dispositions = [r["disposition"] for r in rows]
        assert "success" in dispositions
        assert "exhausted" not in dispositions

    def test_preserves_failed_without_success(self, backend):
        """FAILED disposition kept when no SUCCESS exists for that record."""
        self._insert_disposition(backend, "action_a", "record_1", "failed", "error")

        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        assert len(rows) == 1
        assert rows[0]["disposition"] == "failed"

    def test_preserves_other_dispositions(self, backend):
        """Non-failed/exhausted dispositions are never removed by cleanup."""
        self._insert_disposition(backend, "action_a", "record_1", "filtered", "guard")
        self._insert_disposition(backend, "action_a", "record_1", "success")

        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        dispositions = [r["disposition"] for r in rows]
        assert "filtered" in dispositions
        assert "success" in dispositions

    def test_does_not_remove_across_actions(self, backend):
        """SUCCESS in action_b does not affect FAILED in action_a."""
        self._insert_disposition(backend, "action_a", "record_1", "failed", "error")
        self._insert_disposition(backend, "action_b", "record_1", "success")

        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        assert len(rows) == 1
        assert rows[0]["disposition"] == "failed"

    def test_cleanup_is_idempotent(self, backend):
        """Running cleanup twice produces the same result."""
        self._insert_disposition(backend, "action_a", "record_1", "failed", "error")
        self._insert_disposition(backend, "action_a", "record_1", "success")

        backend._cleanup_stale_dispositions()
        backend._cleanup_stale_dispositions()

        rows = backend.get_disposition("action_a", record_id="record_1")
        dispositions = [r["disposition"] for r in rows]
        assert dispositions == ["success"]


class TestPromptTraceRetention:
    """Tests for prompt trace retention policy."""

    def _insert_trace(self, backend, action, record_id, created_at):
        """Insert a prompt trace with a specific created_at timestamp."""
        with backend._lock:
            backend.connection.execute(
                """
                INSERT OR REPLACE INTO prompt_trace
                (action_name, record_id, attempt, compiled_prompt, created_at)
                VALUES (?, ?, 1, 'test prompt', ?)
                """,
                (action, record_id, created_at),
            )
            backend.connection.commit()

    def test_retains_recent_runs(self, backend):
        """Traces from recent runs within retention window are kept."""
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._insert_trace(backend, "act", "r1", today)
        self._insert_trace(backend, "act", "r2", today)

        backend._enforce_prompt_trace_retention(retention_runs=10)

        traces = backend.get_prompt_traces("act")
        assert len(traces) == 2

    def test_deletes_old_runs_beyond_retention(self, backend):
        """Traces from runs older than retention window are deleted."""
        old_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        mid_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._insert_trace(backend, "act", "r_old", old_date)
        self._insert_trace(backend, "act", "r_mid", mid_date)
        self._insert_trace(backend, "act", "r_new", today)

        # Keep last 2 run-days — old should be deleted
        backend._enforce_prompt_trace_retention(retention_runs=2)

        traces = backend.get_prompt_traces("act")
        record_ids = [t["record_id"] for t in traces]
        assert "r_old" not in record_ids
        assert "r_mid" in record_ids
        assert "r_new" in record_ids

    def test_noop_when_fewer_runs_than_retention(self, backend):
        """No deletion when there are fewer runs than the retention window."""
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._insert_trace(backend, "act", "r1", today)

        backend._enforce_prompt_trace_retention(retention_runs=10)

        traces = backend.get_prompt_traces("act")
        assert len(traces) == 1

    def test_retention_zero_is_noop(self, backend):
        """retention_runs < 1 does nothing."""
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._insert_trace(backend, "act", "r1", today)

        backend._enforce_prompt_trace_retention(retention_runs=0)

        traces = backend.get_prompt_traces("act")
        assert len(traces) == 1


class TestSourceDataTtl:
    """Tests for source data TTL enforcement."""

    def _insert_source_with_age(self, backend, path, guid, days_old):
        """Insert source data with a specific age."""
        created = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")
        with backend._lock:
            backend.connection.execute(
                """
                INSERT OR REPLACE INTO source_data
                (relative_path, source_guid, data, created_at)
                VALUES (?, ?, '{}', ?)
                """,
                (path, guid, created),
            )
            backend.connection.commit()

    def _count_source_rows(self, backend):
        """Count total rows in source_data table."""
        cursor = backend.connection.execute("SELECT COUNT(*) FROM source_data")
        return cursor.fetchone()[0]

    def _get_source_guids(self, backend):
        """Get all source_guids from source_data table."""
        cursor = backend.connection.execute("SELECT source_guid FROM source_data")
        return [row[0] for row in cursor.fetchall()]

    def test_deletes_old_source_data(self, backend):
        """Source data older than TTL is deleted."""
        self._insert_source_with_age(backend, "old.json", "guid_old", days_old=60)
        self._insert_source_with_age(backend, "new.json", "guid_new", days_old=1)

        backend._enforce_source_data_ttl(ttl_days=30)

        guids = self._get_source_guids(backend)
        assert "guid_old" not in guids
        assert "guid_new" in guids

    def test_keeps_data_within_ttl(self, backend):
        """Source data within TTL is preserved."""
        self._insert_source_with_age(backend, "recent.json", "guid_recent", days_old=5)

        backend._enforce_source_data_ttl(ttl_days=30)

        assert self._count_source_rows(backend) == 1

    def test_ttl_zero_is_noop(self, backend):
        """ttl_days < 1 does nothing."""
        self._insert_source_with_age(backend, "old.json", "guid_old", days_old=60)

        backend._enforce_source_data_ttl(ttl_days=0)

        assert self._count_source_rows(backend) == 1

    def test_ttl_none_skipped_in_perform_maintenance(self, backend):
        """perform_maintenance with source_data_ttl_days=None skips TTL enforcement."""
        self._insert_source_with_age(backend, "old.json", "guid_old", days_old=365)

        backend.perform_maintenance(
            prompt_trace_retention_runs=10,
            source_data_ttl_days=None,
        )

        assert self._count_source_rows(backend) == 1


class TestPerformMaintenance:
    """Tests for the orchestrator method that runs all maintenance operations."""

    def test_runs_without_error_on_empty_db(self, backend):
        """perform_maintenance is safe on an empty database."""
        backend.perform_maintenance()

    def test_runs_all_operations(self, backend):
        """perform_maintenance executes WAL checkpoint + disposition cleanup + trace retention."""
        # Write some data to exercise all paths
        backend.write_source("file.json", [{"source_guid": "g1", "data": "test"}])
        # Insert dispositions directly to simulate accumulated records
        with backend._lock:
            backend.connection.execute(
                "INSERT INTO record_disposition (action_name, record_id, disposition, reason, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                ("act", "r1", "failed", "error"),
            )
            backend.connection.execute(
                "INSERT INTO record_disposition (action_name, record_id, disposition, reason, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                ("act", "r1", "success", None),
            )
            backend.connection.commit()

        backend.perform_maintenance(
            prompt_trace_retention_runs=10,
            source_data_ttl_days=None,
        )

        # Stale disposition should be cleaned up
        rows = backend.get_disposition("act", record_id="r1")
        dispositions = [r["disposition"] for r in rows]
        assert "failed" not in dispositions
        assert "success" in dispositions

    def test_is_idempotent(self, backend):
        """Running maintenance multiple times is safe."""
        backend.perform_maintenance()
        backend.perform_maintenance()
        backend.perform_maintenance()
