"""Tests for _enforce_schema: ALTER TABLE ADD COLUMN instead of DROP TABLE."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@contextmanager
def extra_required_columns(backend, table_name, columns):
    """Temporarily add columns to _REQUIRED_COLUMNS, restoring on exit."""
    original = backend._REQUIRED_COLUMNS[table_name].copy()
    backend._REQUIRED_COLUMNS[table_name] = original | set(columns)
    try:
        yield
    finally:
        backend._REQUIRED_COLUMNS[table_name] = original


class TestSchemaMigrationPreservesData:
    """Verify _enforce_schema uses ALTER TABLE, never DROP TABLE."""

    @pytest.fixture
    def backend_with_records(self, tmp_path):
        """Create a backend with 3 target records and 3 dispositions."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()

        cursor = backend.connection.cursor()
        for i in range(3):
            cursor.execute(
                "INSERT INTO target_data (action_name, relative_path, data, record_count) "
                "VALUES (?, ?, ?, ?)",
                (f"action_{i}", f"file_{i}.json", json.dumps([{"id": i}]), 1),
            )
            cursor.execute(
                "INSERT INTO record_disposition (action_name, record_id, disposition, reason, relative_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"action_{i}", f"record_{i}", "SUCCESS", "completed", f"file_{i}.json"),
            )
        backend.connection.commit()

        yield backend
        backend.close()

    def test_alter_table_preserves_target_records(self, backend_with_records):
        """Adding a missing column must not destroy existing target records."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        with extra_required_columns(backend, "target_data", {"updated_at"}):
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 3

            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "updated_at" in columns

            cursor.execute("SELECT updated_at FROM target_data LIMIT 1")
            assert cursor.fetchone()[0] is None

    def test_alter_table_preserves_dispositions(self, backend_with_records):
        """Adding a missing column must not destroy existing dispositions."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        with extra_required_columns(backend, "record_disposition", {"updated_at"}):
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("SELECT COUNT(*) FROM record_disposition")
            assert cursor.fetchone()[0] == 3

            cursor.execute("PRAGMA table_info(record_disposition)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "updated_at" in columns

    def test_multiple_missing_columns(self, backend_with_records):
        """Multiple missing columns are each added individually."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        with extra_required_columns(backend, "target_data", {"col_a", "col_b", "col_c"}):
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert {"col_a", "col_b", "col_c"}.issubset(columns)

            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 3

    def test_no_change_when_schema_matches(self, backend_with_records):
        """No ALTER when existing columns already match required columns."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        cursor.execute("PRAGMA table_info(target_data)")
        columns_before = {row[1] for row in cursor.fetchall()}

        backend._enforce_schema(cursor)

        cursor.execute("PRAGMA table_info(target_data)")
        columns_after = {row[1] for row in cursor.fetchall()}
        assert columns_before == columns_after

    def test_nonexistent_table_skipped(self, tmp_path):
        """Tables not yet created are skipped (CREATE TABLE handles them)."""
        db_path = tmp_path / "agent_io" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend._connection = conn

        cursor = conn.cursor()
        backend._enforce_schema(cursor)
        conn.close()

    def test_idempotent_migration(self, backend_with_records):
        """Running _enforce_schema twice with the same missing column is safe."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        with extra_required_columns(backend, "target_data", {"new_col"}):
            backend._enforce_schema(cursor)
            backend.connection.commit()

            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 3

    def test_full_reinitialize_preserves_data(self, tmp_path):
        """Full initialize() cycle with a new column preserves all records."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()

        cursor = backend.connection.cursor()
        for i in range(3):
            cursor.execute(
                "INSERT INTO target_data (action_name, relative_path, data, record_count) "
                "VALUES (?, ?, ?, ?)",
                (f"action_{i}", f"file_{i}.json", json.dumps([{"id": i}]), 1),
            )
        backend.connection.commit()

        with extra_required_columns(backend, "target_data", {"migrated_col"}):
            backend.initialize()

            cursor = backend.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 3

            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "migrated_col" in columns

        backend.close()
