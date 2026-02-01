"""Integration tests for pluggable storage backend.

Tests the full storage backend lifecycle including:
- Initialization and table creation
- Write/read operations for source and target data
- Deduplication behavior
- Preview and statistics functionality
- Context manager cleanup
"""

import pytest
import tempfile
from pathlib import Path

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class TestSQLiteBackendLifecycle:
    """Test SQLite backend initialization and cleanup."""

    def test_creates_database_file_on_initialize(self):
        """Backend creates database file when initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_workflow" / "agent_io" / "test.db"

            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()

            assert db_path.exists()
            assert backend.backend_type == "sqlite"
            backend.close()

    def test_creates_tables_on_initialize(self):
        """Backend creates source_data and target_data tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()

            # Verify tables exist
            cursor = backend.connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row["name"] for row in cursor.fetchall()]

            assert "source_data" in tables
            assert "target_data" in tables
            backend.close()

    def test_context_manager_cleanup(self):
        """Context manager properly closes connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with SQLiteBackend(str(db_path), "test_workflow") as backend:
                backend.initialize()
                # Connection is active inside context
                assert backend._connection is not None

            # Connection should be closed after context exit
            assert backend._connection is None


class TestTargetDataOperations:
    """Test target data write/read operations."""

    @pytest.fixture
    def backend(self):
        """Create and initialize a test backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()
            yield backend
            backend.close()

    def test_write_and_read_target_data(self, backend):
        """Can write and read target data for a node."""
        test_data = [
            {"content": {"text": "record 1"}, "source_guid": "guid-1"},
            {"content": {"text": "record 2"}, "source_guid": "guid-2"},
        ]

        # Write
        result = backend.write_target("extract_action", "batch_001.json", test_data)
        assert result == "extract_action:batch_001.json"

        # Read
        retrieved = backend.read_target("extract_action", "batch_001.json")
        assert len(retrieved) == 2
        assert retrieved[0]["content"]["text"] == "record 1"
        assert retrieved[1]["source_guid"] == "guid-2"

    def test_write_target_overwrites_existing(self, backend):
        """Writing to same path overwrites existing data."""
        # Write initial data
        backend.write_target("node1", "file.json", [{"id": 1}])

        # Write new data to same path
        backend.write_target("node1", "file.json", [{"id": 2}, {"id": 3}])

        # Should have new data
        retrieved = backend.read_target("node1", "file.json")
        assert len(retrieved) == 2
        assert retrieved[0]["id"] == 2

    def test_read_target_raises_file_not_found(self, backend):
        """Reading non-existent target raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            backend.read_target("nonexistent_node", "missing.json")

        assert "No target data found" in str(exc_info.value)

    def test_list_target_files(self, backend):
        """Can list all target files for a node."""
        backend.write_target("node1", "batch_001.json", [{"id": 1}])
        backend.write_target("node1", "batch_002.json", [{"id": 2}])
        backend.write_target("node2", "batch_001.json", [{"id": 3}])

        node1_files = backend.list_target_files("node1")
        assert len(node1_files) == 2
        assert "batch_001.json" in node1_files
        assert "batch_002.json" in node1_files

        node2_files = backend.list_target_files("node2")
        assert len(node2_files) == 1


class TestSourceDataOperations:
    """Test source data write/read operations with deduplication."""

    @pytest.fixture
    def backend(self):
        """Create and initialize a test backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()
            yield backend
            backend.close()

    def test_write_and_read_source_data(self, backend):
        """Can write and read source data."""
        test_data = [
            {"source_guid": "guid-001", "content": {"text": "source 1"}},
            {"source_guid": "guid-002", "content": {"text": "source 2"}},
        ]

        result = backend.write_source("sources/batch_001.json", test_data)
        assert result == "sources/batch_001.json"

        retrieved = backend.read_source("sources/batch_001.json")
        assert len(retrieved) == 2

    def test_deduplication_skips_existing_guids(self, backend):
        """Deduplication prevents duplicate source_guids."""
        # Write initial data
        backend.write_source(
            "sources/batch.json",
            [{"source_guid": "guid-001", "value": "first"}],
        )

        # Try to write same guid again
        backend.write_source(
            "sources/batch.json",
            [{"source_guid": "guid-001", "value": "duplicate"}],
            enable_deduplication=True,
        )

        # Should still have original value
        retrieved = backend.read_source("sources/batch.json")
        assert len(retrieved) == 1
        assert retrieved[0]["value"] == "first"

    def test_deduplication_disabled_overwrites(self, backend):
        """Disabling deduplication allows overwriting."""
        # Write initial data
        backend.write_source(
            "sources/batch.json",
            [{"source_guid": "guid-001", "value": "first"}],
        )

        # Write same guid with deduplication disabled
        backend.write_source(
            "sources/batch.json",
            [{"source_guid": "guid-001", "value": "updated"}],
            enable_deduplication=False,
        )

        # Should have updated value
        retrieved = backend.read_source("sources/batch.json")
        assert len(retrieved) == 1
        assert retrieved[0]["value"] == "updated"

    def test_read_source_raises_file_not_found(self, backend):
        """Reading non-existent source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            backend.read_source("nonexistent/path.json")

        assert "No source data found" in str(exc_info.value)

    def test_list_source_files(self, backend):
        """Can list all source file paths."""
        backend.write_source(
            "sources/batch_001.json",
            [{"source_guid": "g1", "data": 1}],
        )
        backend.write_source(
            "sources/batch_002.json",
            [{"source_guid": "g2", "data": 2}],
        )

        files = backend.list_source_files()
        assert len(files) == 2
        assert "sources/batch_001.json" in files


class TestPreviewAndStats:
    """Test preview and statistics functionality."""

    @pytest.fixture
    def backend_with_data(self):
        """Create backend with sample data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()

            # Add sample target data
            backend.write_target(
                "extract",
                "batch_001.json",
                [{"id": i, "text": f"record {i}"} for i in range(15)],
            )
            backend.write_target(
                "extract",
                "batch_002.json",
                [{"id": i, "text": f"record {i}"} for i in range(15, 25)],
            )
            backend.write_target(
                "transform",
                "batch_001.json",
                [{"id": i, "result": f"transformed {i}"} for i in range(5)],
            )

            # Add sample source data
            backend.write_source(
                "sources/input.json",
                [{"source_guid": f"guid-{i}", "raw": f"source {i}"} for i in range(10)],
            )

            yield backend
            backend.close()

    def test_preview_target_returns_paginated_records(self, backend_with_data):
        """Preview returns paginated records with metadata."""
        result = backend_with_data.preview_target("extract", limit=5, offset=0)

        assert len(result["records"]) == 5
        assert result["total_count"] == 25  # 15 + 10 from both batches
        assert result["node_name"] == "extract"
        assert len(result["files"]) == 2
        assert result["limit"] == 5
        assert result["offset"] == 0

    def test_preview_target_with_offset(self, backend_with_data):
        """Preview respects offset parameter."""
        result = backend_with_data.preview_target("extract", limit=5, offset=10)

        assert len(result["records"]) == 5
        assert result["offset"] == 10

    def test_preview_target_specific_file(self, backend_with_data):
        """Preview can filter to specific file."""
        result = backend_with_data.preview_target(
            "extract", limit=100, relative_path="batch_001.json"
        )

        assert result["total_count"] == 15

    def test_preview_target_missing_file(self, backend_with_data):
        """Preview handles missing file gracefully."""
        result = backend_with_data.preview_target(
            "extract", relative_path="nonexistent.json"
        )

        assert result["total_count"] == 0
        assert "error" in result

    def test_get_storage_stats(self, backend_with_data):
        """Get storage stats returns correct counts."""
        stats = backend_with_data.get_storage_stats()

        assert stats["source_count"] == 10
        assert stats["target_count"] == 30  # 15 + 10 + 5
        assert "extract" in stats["nodes"]
        assert "transform" in stats["nodes"]
        assert stats["nodes"]["extract"] == 25
        assert stats["nodes"]["transform"] == 5
        assert stats["db_size_bytes"] > 0
        assert "db_path" in stats


class TestConcurrencyAndResilience:
    """Test concurrent access and error handling."""

    def test_multiple_writes_to_same_node(self):
        """Multiple sequential writes to same node work correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with SQLiteBackend(str(db_path), "test_workflow") as backend:
                backend.initialize()

                # Multiple writes to same node, different files
                for i in range(10):
                    backend.write_target(
                        "node1",
                        f"batch_{i:03d}.json",
                        [{"batch": i, "id": j} for j in range(5)],
                    )

                files = backend.list_target_files("node1")
                assert len(files) == 10

    def test_handles_unicode_data(self):
        """Backend correctly handles unicode data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with SQLiteBackend(str(db_path), "test_workflow") as backend:
                backend.initialize()

                test_data = [
                    {"text": "Hello 世界 🌍"},
                    {"text": "Ελληνικά"},
                    {"text": "العربية"},
                ]

                backend.write_target("node1", "unicode.json", test_data)
                retrieved = backend.read_target("node1", "unicode.json")

                assert retrieved[0]["text"] == "Hello 世界 🌍"
                assert retrieved[1]["text"] == "Ελληνικά"
                assert retrieved[2]["text"] == "العربية"

    def test_handles_large_records(self):
        """Backend handles large JSON records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            with SQLiteBackend(str(db_path), "test_workflow") as backend:
                backend.initialize()

                # Create a large record (~1MB of text)
                large_text = "x" * (1024 * 1024)
                test_data = [{"large_field": large_text}]

                backend.write_target("node1", "large.json", test_data)
                retrieved = backend.read_target("node1", "large.json")

                assert len(retrieved[0]["large_field"]) == 1024 * 1024


class TestBackendTypeProperty:
    """Test backend_type property behavior."""

    def test_backend_type_returns_sqlite(self):
        """SQLiteBackend returns 'sqlite' as backend_type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backend = SQLiteBackend(str(db_path), "test_workflow")

            assert backend.backend_type == "sqlite"
            backend.close()


class TestWorkflowIntegration:
    """Test integration with workflow patterns."""

    def test_action_chain_data_flow(self):
        """Simulates data flowing through action chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Action 1: Extract - writes target data
                extract_output = [
                    {"source_guid": "g1", "content": {"raw": "doc1"}},
                    {"source_guid": "g2", "content": {"raw": "doc2"}},
                ]
                backend.write_target("extract", "batch.json", extract_output)

                # Action 2: Transform - reads from extract, writes new target
                extract_data = backend.read_target("extract", "batch.json")
                transform_output = [
                    {**item, "content": {"processed": item["content"]["raw"].upper()}}
                    for item in extract_data
                ]
                backend.write_target("transform", "batch.json", transform_output)

                # Action 3: Load - reads from transform
                transform_data = backend.read_target("transform", "batch.json")

                assert len(transform_data) == 2
                assert transform_data[0]["content"]["processed"] == "DOC1"
                assert transform_data[1]["content"]["processed"] == "DOC2"

    def test_parallel_actions_write_to_different_nodes(self):
        """Parallel actions can write to different nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Simulate parallel writes from different actions
                backend.write_target("action_a", "batch.json", [{"from": "a"}])
                backend.write_target("action_b", "batch.json", [{"from": "b"}])
                backend.write_target("action_c", "batch.json", [{"from": "c"}])

                # Each action's data is separate
                data_a = backend.read_target("action_a", "batch.json")
                data_b = backend.read_target("action_b", "batch.json")
                data_c = backend.read_target("action_c", "batch.json")

                assert data_a[0]["from"] == "a"
                assert data_b[0]["from"] == "b"
                assert data_c[0]["from"] == "c"

    def test_merge_pattern_combines_upstream_data(self):
        """Merge pattern can read from multiple upstream nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Two parallel upstream actions
                backend.write_target("extract_a", "batch.json", [{"id": 1, "src": "a"}])
                backend.write_target("extract_b", "batch.json", [{"id": 2, "src": "b"}])

                # Merge action reads from both
                data_a = backend.read_target("extract_a", "batch.json")
                data_b = backend.read_target("extract_b", "batch.json")
                merged = data_a + data_b

                backend.write_target("merge", "batch.json", merged)

                result = backend.read_target("merge", "batch.json")
                assert len(result) == 2
                assert {r["src"] for r in result} == {"a", "b"}
