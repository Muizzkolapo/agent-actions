"""Tests for _enforce_schema: ALTER TABLE ADD COLUMN instead of DROP TABLE."""

import json
import sqlite3
from unittest.mock import patch

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestSchemaMigrationPreservesData:
    """Verify _enforce_schema uses ALTER TABLE, never DROP TABLE."""

    @pytest.fixture
    def backend_with_records(self, tmp_path):
        """Create a backend with 100 target records and 100 dispositions."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()

        cursor = backend.connection.cursor()
        # Insert 100 target records
        for i in range(100):
            cursor.execute(
                "INSERT INTO target_data (action_name, relative_path, data, record_count) "
                "VALUES (?, ?, ?, ?)",
                (f"action_{i}", f"file_{i}.json", json.dumps([{"id": i}]), 1),
            )
        # Insert 100 dispositions
        for i in range(100):
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

        # Verify records exist before migration
        cursor = backend.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM target_data")
        assert cursor.fetchone()[0] == 100

        # Add a new required column that doesn't exist yet
        original_required = backend._REQUIRED_COLUMNS["target_data"].copy()
        backend._REQUIRED_COLUMNS["target_data"] = original_required | {"updated_at"}

        try:
            # Re-run _enforce_schema (simulating re-initialize)
            backend._enforce_schema(cursor)
            backend.connection.commit()

            # All 100 records must still exist
            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 100

            # New column must be present
            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "updated_at" in columns

            # New column must default to NULL for existing rows
            cursor.execute("SELECT updated_at FROM target_data LIMIT 1")
            assert cursor.fetchone()[0] is None
        finally:
            backend._REQUIRED_COLUMNS["target_data"] = original_required

    def test_alter_table_preserves_dispositions(self, backend_with_records):
        """Adding a missing column must not destroy existing dispositions."""
        backend = backend_with_records

        cursor = backend.connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM record_disposition")
        assert cursor.fetchone()[0] == 100

        original_required = backend._REQUIRED_COLUMNS["record_disposition"].copy()
        backend._REQUIRED_COLUMNS["record_disposition"] = original_required | {"updated_at"}

        try:
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("SELECT COUNT(*) FROM record_disposition")
            assert cursor.fetchone()[0] == 100

            cursor.execute("PRAGMA table_info(record_disposition)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "updated_at" in columns
        finally:
            backend._REQUIRED_COLUMNS["record_disposition"] = original_required

    def test_multiple_missing_columns(self, backend_with_records):
        """Multiple missing columns are each added individually."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        original_required = backend._REQUIRED_COLUMNS["target_data"].copy()
        backend._REQUIRED_COLUMNS["target_data"] = original_required | {"col_a", "col_b", "col_c"}

        try:
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert {"col_a", "col_b", "col_c"}.issubset(columns)

            # Data preserved
            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 100
        finally:
            backend._REQUIRED_COLUMNS["target_data"] = original_required

    def test_no_change_when_schema_matches(self, backend_with_records):
        """No ALTER when existing columns already match required columns."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        # _enforce_schema should be a no-op when schema matches
        with patch("agent_actions.storage.backends.sqlite_backend.logger") as mock_logger:
            backend._enforce_schema(cursor)
            # No info logs about migration
            for call in mock_logger.info.call_args_list:
                assert "ALTER TABLE" not in str(call)

    def test_nonexistent_table_skipped(self, tmp_path):
        """Tables not yet created are skipped (CREATE TABLE handles them)."""
        db_path = tmp_path / "agent_io" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend._connection = conn

        cursor = conn.cursor()
        # Should not raise — just skips nonexistent tables
        backend._enforce_schema(cursor)
        conn.close()

    def test_idempotent_migration(self, backend_with_records):
        """Running _enforce_schema twice with the same missing column is safe."""
        backend = backend_with_records
        cursor = backend.connection.cursor()

        original_required = backend._REQUIRED_COLUMNS["target_data"].copy()
        backend._REQUIRED_COLUMNS["target_data"] = original_required | {"new_col"}

        try:
            # First run adds the column
            backend._enforce_schema(cursor)
            backend.connection.commit()

            # Second run — column already exists, should be a no-op
            backend._enforce_schema(cursor)
            backend.connection.commit()

            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 100
        finally:
            backend._REQUIRED_COLUMNS["target_data"] = original_required

    def test_full_reinitialize_preserves_data(self, tmp_path):
        """Full initialize() cycle with a new column preserves all records."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()

        # Insert records
        cursor = backend.connection.cursor()
        for i in range(50):
            cursor.execute(
                "INSERT INTO target_data (action_name, relative_path, data, record_count) "
                "VALUES (?, ?, ?, ?)",
                (f"action_{i}", f"file_{i}.json", json.dumps([{"id": i}]), 1),
            )
        backend.connection.commit()

        # Add new required column
        original_required = backend._REQUIRED_COLUMNS["target_data"].copy()
        backend._REQUIRED_COLUMNS["target_data"] = original_required | {"migrated_col"}

        try:
            # Re-initialize (as would happen on framework upgrade)
            backend.initialize()

            cursor = backend.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM target_data")
            assert cursor.fetchone()[0] == 50

            cursor.execute("PRAGMA table_info(target_data)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "migrated_col" in columns
        finally:
            backend._REQUIRED_COLUMNS["target_data"] = original_required
            backend.close()
