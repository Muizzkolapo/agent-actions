"""Every SQLiteBackend read holds the backend lock, so parallel sibling actions read safely."""

from unittest.mock import patch

import pytest


def _make_tracking_lock(backend):
    """Return (TrackingLock, acquired_list) for patching backend._lock."""
    acquired: list[str] = []
    original = backend._lock

    class TrackingLock:
        def __enter__(self_inner):
            acquired.append("locked")
            return original.__enter__()

        def __exit__(self_inner, *args):
            return original.__exit__(*args)

    return TrackingLock(), acquired


def _seed_target(backend):
    backend.write_target(
        "action_a", "out.json", [{"_state": "processed", "_state_schema_version": 1, "id": 1}]
    )


def _seed_source(backend):
    backend.write_source("in.json", [{"source_guid": "abc", "val": 1}])


def _seed_disposition(backend):
    backend.set_disposition("action_a", "rec1", "skipped")


class TestSQLiteBackendThreadSafeReads:
    """Every read method holds self._lock during the query."""

    @pytest.mark.parametrize(
        ("seed", "method", "args"),
        [
            pytest.param(_seed_target, "list_target_files", ("action_a",), id="list_target_files"),
            pytest.param(_seed_target, "read_target", ("action_a", "out.json"), id="read_target"),
            pytest.param(_seed_source, "read_source", ("in.json",), id="read_source"),
            pytest.param(_seed_source, "list_source_files", (), id="list_source_files"),
            pytest.param(_seed_disposition, "get_disposition", ("action_a",), id="get_disposition"),
            pytest.param(
                _seed_disposition,
                "has_disposition",
                ("action_a", "skipped"),
                id="has_disposition",
            ),
            pytest.param(_seed_target, "preview_target", ("action_a",), id="preview_target"),
            pytest.param(_seed_target, "get_storage_stats", (), id="get_storage_stats"),
        ],
    )
    def test_read_acquires_lock(self, tmp_path, seed, method, args):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        seed(backend)

        tracking_lock, acquired = _make_tracking_lock(backend)
        with patch.object(backend, "_lock", tracking_lock):
            getattr(backend, method)(*args)

        assert "locked" in acquired, f"{method} must acquire _lock"

    def test_concurrent_reads_return_correct_data(self, tmp_path):
        """Multiple threads reading simultaneously must all return correct data."""
        import concurrent.futures

        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        backend.write_target(
            "upstream",
            "data.json",
            [{"_state": "processed", "_state_schema_version": 1, "val": i} for i in range(50)],
        )

        results: list[list[str]] = []
        errors: list[Exception] = []

        def read_files():
            try:
                results.append(backend.list_target_files("upstream"))
            except Exception as exc:
                errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(read_files) for _ in range(20)]
            concurrent.futures.wait(futures)

        assert not errors, f"Concurrent reads raised: {errors}"
        assert all(r == ["data.json"] for r in results), "All threads must see correct data"
