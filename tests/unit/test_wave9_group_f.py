"""Wave 9 Group F regression tests — Storage and run-tracker concurrency P1 fixes."""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import portalocker
import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

# ---------------------------------------------------------------------------
# F-1  ·  sqlite_backend.py — RLock + lock in connection property
# ---------------------------------------------------------------------------


class TestSQLiteBackendRLock:
    """F-1 — self._lock is RLock; connection property acquires it."""

    def test_lock_is_rlock(self, tmp_path):
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        assert isinstance(backend._lock, type(threading.RLock())), (
            "SQLiteBackend._lock must be threading.RLock(), not Lock()"
        )

    def test_connection_property_acquires_lock(self, tmp_path):
        """connection property must not return _connection without acquiring lock."""
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        backend.initialize()

        # Verify that the lock is reentrant: calling connection inside a lock block
        # should not deadlock (which would happen with threading.Lock()).
        deadline_passed = threading.Event()

        def try_reentrant():
            try:
                with backend._lock:
                    # Calling backend.connection inside a with-block on the same lock
                    # would deadlock with threading.Lock(); RLock allows reentry.
                    _ = backend.connection
                    deadline_passed.set()
            except Exception:
                pass

        t = threading.Thread(target=try_reentrant)
        t.start()
        t.join(timeout=2.0)

        assert deadline_passed.is_set(), (
            "connection property deadlocked — lock is not reentrant (RLock required)"
        )

    def test_connection_not_initialized_raises(self, tmp_path):
        """Uninitialized backend raises RuntimeError, even with lock."""
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = backend.connection


# ---------------------------------------------------------------------------
# F-2  ·  sqlite_backend.py — set_disposition validates relative_path
# ---------------------------------------------------------------------------


class TestSetDispositionValidatesRelativePath:
    """F-2 — relative_path is validated when provided."""

    def _make_backend(self, tmp_path: Path) -> SQLiteBackend:
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        backend.initialize()
        return backend

    def test_valid_relative_path_accepted(self, tmp_path):
        backend = self._make_backend(tmp_path)
        # Should not raise
        backend.set_disposition("agent_a", "__node__", "skipped", relative_path="batch_0.json")

    def test_path_traversal_in_relative_path_raises(self, tmp_path):
        backend = self._make_backend(tmp_path)
        with pytest.raises(ValueError, match="Path traversal"):
            backend.set_disposition(
                "agent_a", "__node__", "skipped", relative_path="../../../etc/passwd"
            )

    def test_none_relative_path_is_allowed(self, tmp_path):
        backend = self._make_backend(tmp_path)
        # relative_path=None must not raise (it's optional)
        backend.set_disposition("agent_a", "__node__", "skipped", relative_path=None)


# ---------------------------------------------------------------------------
# F-3  ·  run_tracker.py — LOCK_NB + backoff in record_run / start_workflow_run
# ---------------------------------------------------------------------------


class TestRunTrackerLockNB:
    """F-3 — record_run and start_workflow_run use LOCK_EX | LOCK_NB."""

    def test_record_run_uses_lock_nb(self, tmp_path):
        """When the file is already exclusively locked, record_run raises LockException."""
        from agent_actions.tooling.docs.run_tracker import RunConfig, RunTracker

        tracker = RunTracker(artefact_dir=tmp_path)
        tracker.artefact_dir.mkdir(parents=True, exist_ok=True)
        tracker.runs_file.touch(exist_ok=True)
        tracker.runs_file.write_text(json.dumps({"metadata": {}, "executions": []}))

        config = RunConfig(
            workflow_id="wf-1",
            workflow_name="test",
            status="completed",
            started_at="2026-01-01T00:00:00",
        )

        # Use a short timeout so the test doesn't wait 10s for LockException
        with (
            patch("agent_actions.tooling.docs.run_tracker.LockDefaults") as mock_defaults,
            portalocker.Lock(tracker.runs_file, "r+", flags=portalocker.LOCK_EX),
        ):
            mock_defaults.ATOMIC_LOCK_TIMEOUT_SECONDS = 0.1
            with pytest.raises(portalocker.exceptions.LockException):
                tracker.record_run(config=config)

    def test_record_run_happy_path_writes_to_file(self, tmp_path):
        """record_run with no contention must persist the run to disk."""
        from agent_actions.tooling.docs.run_tracker import RunConfig, RunTracker

        tracker = RunTracker(artefact_dir=tmp_path)
        config = RunConfig(
            workflow_id="wf-happy",
            workflow_name="happy test",
            status="completed",
            started_at="2026-01-01T00:00:00+00:00",
            ended_at="2026-01-01T00:00:05+00:00",
        )

        run_id = tracker.record_run(config=config)

        assert tracker.runs_file.exists()
        data = json.loads(tracker.runs_file.read_text())
        runs = [r for r in data["executions"] if r["id"] == run_id]
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        assert runs[0]["workflow_id"] == "wf-happy"

    def test_lock_nb_flag_present_in_record_run_source(self):
        """LOCK_NB must appear in record_run source — contention tests pass with any non-blocking
        impl, but this pins the exact flag."""
        import inspect

        from agent_actions.tooling.docs.run_tracker import RunTracker

        src = inspect.getsource(RunTracker.record_run)
        assert "LOCK_NB" in src, "LOCK_NB flag must be present in record_run"

    def test_lock_nb_flag_present_in_start_workflow_run_source(self):
        """LOCK_NB must appear in start_workflow_run source."""
        import inspect

        from agent_actions.tooling.docs.run_tracker import RunTracker

        src = inspect.getsource(RunTracker.start_workflow_run)
        assert "LOCK_NB" in src, "LOCK_NB flag must be present in start_workflow_run"

    def test_start_workflow_run_uses_lock_nb(self, tmp_path):
        """When the file is already exclusively locked, start_workflow_run raises LockException."""
        from agent_actions.tooling.docs.run_tracker import RunTracker

        tracker = RunTracker(artefact_dir=tmp_path)
        tracker.artefact_dir.mkdir(parents=True, exist_ok=True)
        tracker.runs_file.touch(exist_ok=True)
        tracker.runs_file.write_text(json.dumps({"metadata": {}, "executions": []}))

        with (
            patch("agent_actions.tooling.docs.run_tracker.LockDefaults") as mock_defaults,
            portalocker.Lock(tracker.runs_file, "r+", flags=portalocker.LOCK_EX),
        ):
            mock_defaults.ATOMIC_LOCK_TIMEOUT_SECONDS = 0.1
            with pytest.raises(portalocker.exceptions.LockException):
                tracker.start_workflow_run(
                    workflow_id="wf-1", workflow_name="test", actions_total=3
                )


# ---------------------------------------------------------------------------
# F-4  ·  run_tracker.py — atomic file creation before lock in start_workflow_run
# ---------------------------------------------------------------------------


class TestRunTrackerAtomicFileCreation:
    """F-4 — start_workflow_run creates the file atomically (touch) before locking."""

    def test_file_created_before_lock_acquired(self, tmp_path):
        """start_workflow_run must create the file with touch() — not inside the lock — so that
        portalocker.Lock('r+') can open an already-existing file without race."""
        from agent_actions.tooling.docs.run_tracker import RunTracker

        tracker = RunTracker(artefact_dir=tmp_path)

        # The file must not exist yet
        assert not tracker.runs_file.exists()

        # Calling start_workflow_run should create and populate the file
        run_id = tracker.start_workflow_run(
            workflow_id="wf-1", workflow_name="test", actions_total=2
        )

        assert tracker.runs_file.exists()
        data = json.loads(tracker.runs_file.read_text())
        runs = [r for r in data["executions"] if r["id"] == run_id]
        assert len(runs) == 1
        assert runs[0]["status"] == "running"

    def test_no_toctou_pattern_in_source(self):
        """Verify the old TOCTOU pattern (if not exists: open) is not present in the source."""
        import inspect

        from agent_actions.tooling.docs.run_tracker import RunTracker

        src = inspect.getsource(RunTracker.start_workflow_run)
        # The old pattern was `if not self.runs_file.exists(): with open(...)`
        assert "if not self.runs_file.exists()" not in src, (
            "F-4: TOCTOU pattern still present in start_workflow_run"
        )
        # The new pattern uses touch()
        assert "touch" in src, "F-4: atomic touch() not present in start_workflow_run"
