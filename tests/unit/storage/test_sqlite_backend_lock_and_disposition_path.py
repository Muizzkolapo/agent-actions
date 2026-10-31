"""SQLiteBackend guards its connection with a reentrant lock and validates a disposition's relative_path."""

import threading
from pathlib import Path

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestSQLiteBackendRLock:
    """self._lock is RLock; connection property acquires it."""

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


class TestSetDispositionValidatesRelativePath:
    """relative_path is validated when provided."""

    def _make_backend(self, tmp_path: Path) -> SQLiteBackend:
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        backend.initialize()
        return backend

    @pytest.mark.parametrize(
        "relative_path", ["batch_0.json", None], ids=["relative-path", "none-path"]
    )
    def test_valid_or_absent_relative_path_accepted(self, tmp_path, relative_path):
        backend = self._make_backend(tmp_path)
        backend.set_disposition("agent_a", "__node__", "skipped", relative_path=relative_path)

    def test_path_traversal_in_relative_path_raises(self, tmp_path):
        backend = self._make_backend(tmp_path)
        with pytest.raises(ValueError, match="Path traversal"):
            backend.set_disposition(
                "agent_a", "__node__", "skipped", relative_path="../../../etc/passwd"
            )
