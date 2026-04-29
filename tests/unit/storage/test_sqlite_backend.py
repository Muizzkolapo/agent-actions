"""Tests for SQLite storage backend."""

import pytest

from agent_actions.storage import BACKENDS, get_storage_backend
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestStorageBackendFactory:
    """Test storage backend factory function."""

    def test_get_storage_backend_creates_sqlite(self, tmp_path):
        """Test that factory creates SQLite backend."""
        backend = get_storage_backend(
            workflow_path=str(tmp_path),
            workflow_name="test_workflow",
            backend_type="sqlite",
        )
        assert isinstance(backend, SQLiteBackend)

    def test_get_storage_backend_unknown_type_raises(self, tmp_path):
        """Test that unknown backend type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_storage_backend(
                workflow_path=str(tmp_path),
                workflow_name="test_workflow",
                backend_type="unknown",
            )
        assert "Unknown storage backend" in str(exc_info.value)

    def test_backends_registry_contains_sqlite(self):
        """Test that SQLite is registered in BACKENDS."""
        assert "sqlite" in BACKENDS
        assert BACKENDS["sqlite"] is SQLiteBackend


class TestSQLiteBackend:
    """Test SQLite backend implementation."""

    @pytest.fixture
    def backend(self, tmp_path):
        """Create a fresh SQLite backend for testing."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_initialize_creates_tables(self, tmp_path):
        """Test that initialize creates required tables."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()

        # Check tables exist
        cursor = backend.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}

        assert "source_data" in tables
        assert "target_data" in tables
        assert "record_disposition" in tables
        backend.close()

    def test_write_and_read_target(self, backend):
        """Test writing and reading target data."""
        data = [
            {"target_id": "t1", "content": {"field1": "value1"}},
            {"target_id": "t2", "content": {"field2": "value2"}},
        ]

        # Write target data
        result = backend.write_target("node_1", "batch_001.json", data)
        assert result == "node_1:batch_001.json"

        # Read target data
        read_data = backend.read_target("node_1", "batch_001.json")
        assert read_data == data

    def test_read_target_not_found_raises(self, backend):
        """Test that reading non-existent target raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            backend.read_target("node_1", "nonexistent.json")

    def test_write_and_read_source(self, backend):
        """Test writing and reading source data."""
        data = [
            {"source_guid": "guid1", "content": {"input": "data1"}},
            {"source_guid": "guid2", "content": {"input": "data2"}},
        ]

        # Write source data
        result = backend.write_source("batch_001", data)
        assert result == "batch_001"

        # Read source data
        read_data = backend.read_source("batch_001")
        assert len(read_data) == 2
        assert read_data[0]["source_guid"] == "guid1"
        assert read_data[1]["source_guid"] == "guid2"

    def test_read_source_not_found_raises(self, backend):
        """Test that reading non-existent source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            backend.read_source("nonexistent")

    def test_write_source_deduplication(self, backend):
        """Test that duplicate source_guids are deduplicated."""
        data1 = [{"source_guid": "guid1", "content": {"v": "original"}}]
        data2 = [
            {"source_guid": "guid1", "content": {"v": "duplicate"}},  # Should be ignored
            {"source_guid": "guid2", "content": {"v": "new"}},  # Should be added
        ]

        backend.write_source("batch_001", data1, enable_deduplication=True)
        backend.write_source("batch_001", data2, enable_deduplication=True)

        read_data = backend.read_source("batch_001")
        assert len(read_data) == 2

        # Original should be preserved, duplicate ignored
        guids = {item["source_guid"] for item in read_data}
        assert guids == {"guid1", "guid2"}

        # Original value should be kept
        guid1_item = next(item for item in read_data if item["source_guid"] == "guid1")
        assert guid1_item["content"]["v"] == "original"

    def test_write_source_no_deduplication(self, backend):
        """Test that deduplication can be disabled."""
        data1 = [{"source_guid": "guid1", "content": {"v": "original"}}]
        data2 = [{"source_guid": "guid1", "content": {"v": "updated"}}]

        backend.write_source("batch_001", data1, enable_deduplication=False)
        backend.write_source("batch_001", data2, enable_deduplication=False)

        read_data = backend.read_source("batch_001")
        # With no dedup, should have only one record (replaced)
        assert len(read_data) == 1
        assert read_data[0]["content"]["v"] == "updated"

    def test_list_target_files(self, backend):
        """Test listing target files for a node."""
        backend.write_target("node_1", "file1.json", [{"id": 1}])
        backend.write_target("node_1", "file2.json", [{"id": 2}])
        backend.write_target("node_2", "file3.json", [{"id": 3}])

        files = backend.list_target_files("node_1")
        assert sorted(files) == ["file1.json", "file2.json"]

        files = backend.list_target_files("node_2")
        assert files == ["file3.json"]

    def test_list_source_files(self, backend):
        """Test listing source files."""
        backend.write_source("batch_001", [{"source_guid": "g1", "d": 1}])
        backend.write_source("batch_002", [{"source_guid": "g2", "d": 2}])

        files = backend.list_source_files()
        assert sorted(files) == ["batch_001", "batch_002"]

    def test_context_manager(self, tmp_path):
        """Test that backend works as context manager."""
        db_path = tmp_path / "agent_io" / "test.db"

        with SQLiteBackend(str(db_path), "test_workflow") as backend:
            backend.initialize()
            backend.write_target("node_1", "file.json", [{"id": 1}])

        # Connection should be closed
        assert backend._connection is None

    def test_target_update_replaces_data(self, backend):
        """Test that writing to same target path replaces data."""
        backend.write_target("node_1", "file.json", [{"v": "original"}])
        backend.write_target("node_1", "file.json", [{"v": "updated"}])

        data = backend.read_target("node_1", "file.json")
        assert data == [{"v": "updated"}]


class TestDispositionMethods:
    """Test record disposition CRUD operations."""

    @pytest.fixture
    def backend(self, tmp_path):
        """Create a fresh SQLite backend for testing."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_set_and_get_disposition(self, backend):
        """Test writing and reading a disposition record."""
        backend.set_disposition(
            "node_1", NODE_LEVEL_RECORD_ID, "passthrough", reason="All tombstoned"
        )

        results = backend.get_disposition("node_1")
        assert len(results) == 1
        assert results[0]["action_name"] == "node_1"
        assert results[0]["record_id"] == NODE_LEVEL_RECORD_ID
        assert results[0]["disposition"] == "passthrough"
        assert results[0]["reason"] == "All tombstoned"

    def test_set_disposition_upserts(self, backend):
        """Test that setting the same disposition replaces it."""
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough", reason="first")
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough", reason="second")

        results = backend.get_disposition("node_1")
        assert len(results) == 1
        assert results[0]["reason"] == "second"

    def test_get_disposition_filters_by_record_id(self, backend):
        """Test filtering dispositions by record_id."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")
        backend.set_disposition("node_1", "rec_2", "guard_filtered")
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")

        results = backend.get_disposition("node_1", record_id="rec_1")
        assert len(results) == 1
        assert results[0]["record_id"] == "rec_1"

    def test_get_disposition_filters_by_disposition(self, backend):
        """Test filtering dispositions by disposition type."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")

        results = backend.get_disposition("node_1", disposition="passthrough")
        assert len(results) == 1
        assert results[0]["disposition"] == "passthrough"

    def test_has_disposition_returns_true(self, backend):
        """Test has_disposition returns True when disposition exists."""
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")
        assert backend.has_disposition("node_1", "passthrough") is True

    def test_has_disposition_returns_false(self, backend):
        """Test has_disposition returns False when disposition does not exist."""
        assert backend.has_disposition("node_1", "passthrough") is False

    def test_has_disposition_with_record_id(self, backend):
        """Test has_disposition filters by record_id."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")

        assert backend.has_disposition("node_1", "guard_filtered", record_id="rec_1") is True
        assert backend.has_disposition("node_1", "guard_filtered", record_id="rec_2") is False

    def test_clear_disposition_all_for_node(self, backend):
        """Test clearing all dispositions for a node."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")
        backend.set_disposition("node_2", NODE_LEVEL_RECORD_ID, "passthrough")

        deleted = backend.clear_disposition("node_1")
        assert deleted == 2

        # node_1 should be empty
        assert backend.get_disposition("node_1") == []
        # node_2 should be untouched
        assert len(backend.get_disposition("node_2")) == 1

    def test_clear_disposition_by_type(self, backend):
        """Test clearing specific disposition type for a node."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")

        deleted = backend.clear_disposition("node_1", disposition="passthrough")
        assert deleted == 1

        remaining = backend.get_disposition("node_1")
        assert len(remaining) == 1
        assert remaining[0]["disposition"] == "guard_filtered"

    def test_clear_disposition_by_record_id(self, backend):
        """Test clearing dispositions for a specific record."""
        backend.set_disposition("node_1", "rec_1", "guard_filtered")
        backend.set_disposition("node_1", "rec_2", "guard_filtered")

        deleted = backend.clear_disposition("node_1", record_id="rec_1")
        assert deleted == 1

        remaining = backend.get_disposition("node_1")
        assert len(remaining) == 1
        assert remaining[0]["record_id"] == "rec_2"

    def test_set_disposition_with_relative_path(self, backend):
        """Test that relative_path is stored correctly."""
        backend.set_disposition(
            "node_1",
            "rec_1",
            "exhausted",
            reason="Retry limit reached",
            relative_path="batch_001.json",
        )

        results = backend.get_disposition("node_1")
        assert results[0]["relative_path"] == "batch_001.json"

    def test_disposition_in_storage_stats(self, backend):
        """Test that storage stats include disposition count."""
        backend.set_disposition("node_1", NODE_LEVEL_RECORD_ID, "passthrough")
        backend.set_disposition("node_1", "rec_1", "guard_filtered")

        stats = backend.get_storage_stats()
        assert stats["disposition_count"] == 2

    def test_empty_disposition_returns_empty_list(self, backend):
        """Test get_disposition returns empty list for non-existent node."""
        results = backend.get_disposition("nonexistent")
        assert results == []

    def test_invalid_disposition_rejected(self, backend):
        """Test that set_disposition rejects unknown disposition strings."""
        with pytest.raises(ValueError, match="Invalid disposition"):
            backend.set_disposition("node_1", "rec_1", "typo_disposition")


class TestValidation:
    """Tests for input validation and safety checks."""

    def test_connection_raises_if_not_initialized(self, tmp_path):
        """Test that accessing connection before initialize() raises RuntimeError."""
        backend = SQLiteBackend(str(tmp_path / "test.db"), "wf")
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = backend.connection

    @pytest.fixture
    def backend(self, tmp_path):
        """Create a fresh SQLite backend for testing."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_path_traversal_rejected_in_write_target(self, backend):
        """Test that path traversal components are rejected."""
        with pytest.raises(ValueError, match="Path traversal"):
            backend.write_target("node_1", "../../etc/passwd", [{}])

    def test_path_traversal_rejected_in_action_name(self, backend):
        """Test that path traversal is also rejected in action_name."""
        with pytest.raises(ValueError, match="Path traversal"):
            backend.write_target("../evil", "file.json", [{}])

    def test_path_with_dots_but_no_traversal_allowed(self, backend):
        """Test that paths with dots (but not ..) are still valid."""
        backend.write_target("node_1", "file.v2.json", [{"id": 1}])
        assert backend.read_target("node_1", "file.v2.json") == [{"id": 1}]

    def test_relative_path_with_spaces_allowed(self, backend):
        """Test that filenames with spaces are accepted."""
        backend.write_target("node_1", "my file.json", [{"id": 1}])
        assert backend.read_target("node_1", "my file.json") == [{"id": 1}]

    def test_whitespace_only_path_rejected(self, backend):
        """Test that whitespace-only relative_path is rejected."""
        with pytest.raises(ValueError, match="Empty"):
            backend.write_target("node_1", "   ", [{}])

    def test_whitespace_only_action_name_rejected(self, backend):
        """Test that whitespace-only action_name is rejected."""
        with pytest.raises(ValueError, match="Empty"):
            backend.write_target(" ", "file.json", [{}])

    def test_leading_trailing_spaces_in_path_allowed(self, backend):
        """Test that leading/trailing spaces in paths are accepted."""
        backend.write_target("node_1", " file.json ", [{"id": 1}])
        assert backend.read_target("node_1", " file.json ") == [{"id": 1}]

    def test_space_in_action_name_allowed(self, backend):
        """Test that spaces in action_name are accepted."""
        backend.write_target("node 1", "file.json", [{"id": 1}])
        assert backend.read_target("node 1", "file.json") == [{"id": 1}]

    def test_invalid_character_rejected(self, backend):
        """Test that characters outside the allowlist are rejected."""
        with pytest.raises(ValueError, match="Invalid characters"):
            backend.write_target("node_1", "file;name.json", [{}])


class TestWriteSourceDropGuard:
    """Tests for write_source raising on silently dropped records."""

    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_all_records_missing_source_guid_raises(self, backend):
        """write_source raises ValueError when every record lacks source_guid."""
        data = [{"content": "no_guid"}, {"content": "also_no_guid"}]
        with pytest.raises(ValueError, match="dropped"):
            backend.write_source("batch_001", data)

    def test_mix_valid_and_invalid_records_succeeds(self, backend):
        """write_source succeeds when at least one record has source_guid."""
        data = [
            {"source_guid": "g1", "content": "valid"},
            {"content": "no_guid"},
        ]
        result = backend.write_source("batch_001", data)
        assert result == "batch_001"

    def test_empty_data_list_succeeds(self, backend):
        """write_source succeeds with empty data (nothing to drop)."""
        result = backend.write_source("batch_001", [])
        assert result == "batch_001"

    def test_all_duplicates_dedup_does_not_raise(self, backend):
        """write_source succeeds when all records are dedup-skipped."""
        data = [{"source_guid": "g1", "content": "original"}]
        backend.write_source("batch_001", data)
        # Second write: same guid, dedup enabled → skipped, not dropped
        result = backend.write_source("batch_001", data, enable_deduplication=True)
        assert result == "batch_001"


class TestPreviewTargetNullRecordCount:
    """Tests for preview_target fallback when record_count IS NULL."""

    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_null_record_count_uses_json_length(self, backend):
        """preview_target computes correct count from JSON when record_count IS NULL."""
        import json

        records = [{"id": 1}, {"id": 2}, {"id": 3}]
        # Insert directly with NULL record_count to simulate legacy data
        backend.connection.execute(
            "INSERT INTO target_data (action_name, relative_path, data, record_count) "
            "VALUES (?, ?, ?, NULL)",
            ("node_1", "legacy.json", json.dumps(records)),
        )
        backend.connection.commit()

        result = backend.preview_target("node_1")
        assert result["total_count"] == 3
        assert len(result["records"]) == 3


class TestGetStorageStatsNullRecordCount:
    """Tests for get_storage_stats with NULL record_count values."""

    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_null_record_count_returns_zero_not_none(self, backend):
        """Per-node stats return 0 (not None) when all record_count values are NULL."""
        import json

        backend.connection.execute(
            "INSERT INTO target_data (action_name, relative_path, data, record_count) "
            "VALUES (?, ?, ?, NULL)",
            ("node_1", "file.json", json.dumps([{"id": 1}])),
        )
        backend.connection.commit()

        stats = backend.get_storage_stats()
        assert stats["nodes"]["node_1"] == 0
        assert isinstance(stats["nodes"]["node_1"], int)

    def test_mixed_null_and_populated_record_count(self, backend):
        """Per-node stats sum correctly when mixing NULL and populated record_count."""
        import json

        backend.connection.execute(
            "INSERT INTO target_data (action_name, relative_path, data, record_count) "
            "VALUES (?, ?, ?, NULL)",
            ("node_1", "legacy.json", json.dumps([{"id": 1}])),
        )
        backend.write_target("node_1", "new.json", [{"id": 2}, {"id": 3}])

        stats = backend.get_storage_stats()
        # SUM ignores NULLs: only the non-NULL row (2) is summed
        assert stats["nodes"]["node_1"] == 2


class TestSetDispositionRecordIdValidation:
    """Tests for record_id validation in disposition methods."""

    @pytest.fixture
    def backend(self, tmp_path):
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        yield backend
        backend.close()

    def test_path_traversal_record_id_rejected(self, backend):
        """set_disposition rejects path-traversal record_id."""
        with pytest.raises(ValueError, match="Path traversal"):
            backend.set_disposition("node_1", "../../etc/passwd", "guard_filtered")

    def test_empty_record_id_rejected(self, backend):
        """set_disposition rejects empty record_id."""
        with pytest.raises(ValueError, match="Empty"):
            backend.set_disposition("node_1", "", "guard_filtered")

    def test_invalid_chars_in_record_id_rejected(self, backend):
        """set_disposition rejects record_id with invalid characters."""
        with pytest.raises(ValueError, match="Invalid characters"):
            backend.set_disposition("node_1", "rec;id", "guard_filtered")

    def test_uuid_style_record_id_accepted(self, backend):
        """set_disposition accepts UUID-style record_id (hyphens allowed)."""
        backend.set_disposition("node_1", "550e8400-e29b-41d4-a716-446655440000", "guard_filtered")
        results = backend.get_disposition("node_1")
        assert len(results) == 1

    def test_get_disposition_validates_record_id(self, backend):
        """get_disposition rejects invalid record_id filter."""
        with pytest.raises(ValueError, match="Path traversal"):
            backend.get_disposition("node_1", record_id="../../etc/passwd")

    def test_has_disposition_validates_record_id(self, backend):
        """has_disposition rejects invalid record_id filter."""
        with pytest.raises(ValueError, match="Invalid characters"):
            backend.has_disposition("node_1", "guard_filtered", record_id="rec;id")

    def test_clear_disposition_validates_record_id(self, backend):
        """clear_disposition rejects invalid record_id filter."""
        with pytest.raises(ValueError, match="Path traversal"):
            backend.clear_disposition("node_1", record_id="../../etc/passwd")


class TestCloseThreadSafety:
    """Tests for close() acquiring the lock."""

    def test_double_close_is_safe(self, tmp_path):
        """Calling close() twice does not raise."""
        db_path = tmp_path / "agent_io" / "test.db"
        backend = SQLiteBackend(str(db_path), "test_workflow")
        backend.initialize()
        backend.close()
        backend.close()  # Should not raise
        assert backend._connection is None


class TestServiceInitSqliteError:
    """Tests for service_init catching sqlite3.Error."""

    def test_sqlite_error_caught_and_reraised(self):
        """initialize_storage_backend catches sqlite3.Error with structured logging."""
        import sqlite3
        from unittest.mock import MagicMock, patch

        from agent_actions.workflow.service_init import initialize_storage_backend

        config = MagicMock()
        config.paths.constructor_path = "a/b/c.yml"
        metadata = MagicMock()
        metadata.agent_name = "test_agent"
        console = MagicMock()

        mock_backend = MagicMock()
        mock_backend.initialize.side_effect = sqlite3.OperationalError("disk I/O error")

        with patch(
            "agent_actions.workflow.service_init.get_storage_backend",
            return_value=mock_backend,
        ):
            with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                initialize_storage_backend(config, metadata, console)

        # Verify user-facing error message was printed
        console.print.assert_called()
        error_output = console.print.call_args[0][0]
        assert "Storage backend failed" in error_output
