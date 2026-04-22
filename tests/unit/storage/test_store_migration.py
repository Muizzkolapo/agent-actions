"""Tests for auto-migration of .db from target/ to store/."""

import sqlite3

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestStoreMigration:
    """Verify auto-migration moves .db from legacy target/ to store/ on initialize()."""

    def _make_legacy_db(self, tmp_path, workflow_name="test_workflow"):
        """Create a real SQLite db in the legacy target/ location."""
        legacy_dir = tmp_path / "agent_io" / "target"
        legacy_dir.mkdir(parents=True)
        legacy_path = legacy_dir / f"{workflow_name}.db"
        conn = sqlite3.connect(str(legacy_path))
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO marker (id) VALUES (42)")
        conn.commit()
        conn.close()
        return legacy_path

    def test_fresh_project_no_legacy(self, tmp_path):
        """Fresh project: no legacy db — store/ created, db initialized normally."""
        store_path = tmp_path / "agent_io" / "store" / "wf.db"
        backend = SQLiteBackend(str(store_path), "wf")
        backend.initialize()

        assert store_path.exists()
        # Tables were created — verify standard tables exist
        cursor = backend.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        assert "source_data" in tables
        assert "target_data" in tables
        assert "record_disposition" in tables
        backend.close()

    def test_legacy_db_migrated_to_store(self, tmp_path):
        """Legacy project: db in target/, not in store/ — auto-migrated."""
        legacy_path = self._make_legacy_db(tmp_path)
        assert legacy_path.exists()

        store_path = tmp_path / "agent_io" / "store" / "test_workflow.db"
        backend = SQLiteBackend(str(store_path), "test_workflow")
        backend.initialize()

        # Legacy file moved, store file exists
        assert not legacy_path.exists()
        assert store_path.exists()

        # Data survived migration — the marker table and row are intact
        cursor = backend.connection.cursor()
        cursor.execute("SELECT id FROM marker")
        assert cursor.fetchone()[0] == 42
        backend.close()

    def test_already_migrated_db_in_store(self, tmp_path):
        """Already migrated: db in store/ — no migration attempted, used as-is."""
        store_dir = tmp_path / "agent_io" / "store"
        store_dir.mkdir(parents=True)
        store_path = store_dir / "wf.db"
        conn = sqlite3.connect(str(store_path))
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO marker (id) VALUES (99)")
        conn.commit()
        conn.close()

        backend = SQLiteBackend(str(store_path), "wf")
        backend.initialize()

        # Data is the original store data, not overwritten
        cursor = backend.connection.cursor()
        cursor.execute("SELECT id FROM marker")
        assert cursor.fetchone()[0] == 99
        backend.close()

    def test_both_exist_store_takes_precedence(self, tmp_path):
        """Both exist: store/ db takes precedence, target/ db ignored."""
        # Create legacy db with marker=1
        legacy_path = self._make_legacy_db(tmp_path)

        # Create store db with marker=2
        store_dir = tmp_path / "agent_io" / "store"
        store_dir.mkdir(parents=True)
        store_path = store_dir / "test_workflow.db"
        conn = sqlite3.connect(str(store_path))
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO marker (id) VALUES (2)")
        conn.commit()
        conn.close()

        backend = SQLiteBackend(str(store_path), "test_workflow")
        backend.initialize()

        # Store db is used (marker=2), legacy db untouched
        cursor = backend.connection.cursor()
        cursor.execute("SELECT id FROM marker")
        assert cursor.fetchone()[0] == 2
        assert legacy_path.exists()  # legacy not deleted when store already exists
        backend.close()

    def test_legacy_path_does_not_exist(self, tmp_path):
        """Legacy path doesn't exist — no error, db initialized fresh in store/."""
        # target/ dir doesn't even exist
        store_path = tmp_path / "agent_io" / "store" / "wf.db"
        assert not (tmp_path / "agent_io" / "target").exists()

        backend = SQLiteBackend(str(store_path), "wf")
        backend.initialize()

        assert store_path.exists()
        # Functional — standard tables exist
        cursor = backend.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {row[0] for row in cursor.fetchall()}
        assert "source_data" in tables
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
