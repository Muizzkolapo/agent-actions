"""Tests for SQLiteBackend.delete_target()."""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestDeleteTarget:
    """Tests for delete_target() method."""

    @pytest.fixture
    def backend(self, tmp_path):
        """Create a fresh SQLite backend for testing."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_deletes_matching_rows_returns_count(self, backend):
        """Deletes matching rows and returns the count."""
        backend.write_target("action_a", "batch_001.json", [{"id": 1}])
        backend.write_target("action_a", "batch_002.json", [{"id": 2}])
        backend.write_target("action_b", "batch_001.json", [{"id": 3}])

        deleted = backend.delete_target("action_a")

        assert deleted == 2
        assert backend.list_target_files("action_a") == []
        # action_b data should remain
        remaining = backend.list_target_files("action_b")
        assert remaining == ["batch_001.json"]

    def test_returns_zero_when_no_matching_rows(self, backend):
        """Returns 0 when no matching rows exist."""
        deleted = backend.delete_target("nonexistent_action")
        assert deleted == 0


class TestDeleteTargetFiles:
    """An action re-run without one of its inputs deletes what it stored for that one."""

    @pytest.fixture
    def backend(self, tmp_path):
        backend = SQLiteBackend(str(tmp_path / "test.db"), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_only_the_files_named_go(self, backend):
        backend.write_target("action_a", "gone.json", [{"id": 1}])
        backend.write_target("action_a", "kept.json", [{"id": 2}])
        backend.write_target("action_b", "gone.json", [{"id": 3}])

        deleted = backend.delete_target_files("action_a", ["gone.json"])

        assert deleted == 1
        assert backend.list_target_files("action_a") == ["kept.json"]
        assert backend.list_target_files("action_b") == ["gone.json"]

    def test_a_file_read_before_the_delete_is_not_served_after_it(self, backend):
        """Reads are cached per file, and nothing else would clear the entry."""
        backend.write_target("action_a", "gone.json", [{"id": 1, "_state": "processed"}])
        assert backend.read_target("action_a", "gone.json")

        backend.delete_target_files("action_a", ["gone.json"])

        with pytest.raises(FileNotFoundError):
            backend.read_target("action_a", "gone.json")

    def test_naming_nothing_deletes_nothing(self, backend):
        backend.write_target("action_a", "kept.json", [{"id": 1}])

        assert backend.delete_target_files("action_a", []) == 0
        assert backend.list_target_files("action_a") == ["kept.json"]
