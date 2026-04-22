"""Tests for .db storage in store/ directory."""

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestStoreDirectory:
    """Verify the database is created under store/, not target/."""

    def test_db_created_in_store(self, tmp_path):
        """initialize() creates the db under agent_io/store/."""
        store_path = tmp_path / "agent_io" / "store" / "wf.db"
        backend = SQLiteBackend(str(store_path), "wf")
        backend.initialize()

        assert store_path.exists()
        assert store_path.parent.name == "store"
        cursor = backend.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        assert "source_data" in tables
        assert "target_data" in tables
        assert "record_disposition" in tables
        backend.close()

    def test_factory_uses_store_path(self, tmp_path):
        """get_storage_backend() constructs the db path under store/, not target/."""
        from agent_actions.storage import get_storage_backend

        backend = get_storage_backend(
            workflow_path=str(tmp_path),
            workflow_name="my_wf",
        )
        assert "store" in str(backend.db_path)
        assert "target" not in str(backend.db_path)
        expected = tmp_path / "agent_io" / "store" / "my_wf.db"
        assert backend.db_path == expected
