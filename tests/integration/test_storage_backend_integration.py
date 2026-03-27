"""Integration tests for pluggable storage backend.

Tests the full storage backend lifecycle including:
- Initialization and table creation
- Write/read operations for source and target data
- Deduplication behavior
- Preview and statistics functionality
- Context manager cleanup
"""

import tempfile
from pathlib import Path

import pytest

from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
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
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
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
        assert result["action_name"] == "extract"
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
        result = backend_with_data.preview_target("extract", relative_path="nonexistent.json")

        assert result["total_count"] == 0
        assert "error" in result

    def test_preview_target_does_not_mutate_stored_data(self, backend_with_data):
        """Preview should not mutate the original stored records."""
        # Get original data
        original = backend_with_data.read_target("extract", "batch_001.json")
        original_keys = set(original[0].keys())

        # Preview adds _file key to returned records
        result = backend_with_data.preview_target(
            "extract", limit=5, relative_path="batch_001.json"
        )
        assert "_file" in result["records"][0]

        # Re-read original data - should be unchanged (no _file key)
        after = backend_with_data.read_target("extract", "batch_001.json")
        assert set(after[0].keys()) == original_keys
        assert "_file" not in after[0]

    def test_preview_target_large_offset_skips_files(self, backend_with_data):
        """Preview with large offset correctly skips entire files.

        The extract node has:
        - batch_001.json: 15 records (ids 0-14)
        - batch_002.json: 10 records (ids 15-24)

        With offset=15, we should skip batch_001.json entirely and
        start from batch_002.json.
        """
        # Offset of 15 should skip all 15 records from batch_001.json
        result = backend_with_data.preview_target("extract", limit=5, offset=15)

        assert len(result["records"]) == 5
        assert result["total_count"] == 25

        # All returned records should be from batch_002.json
        for record in result["records"]:
            assert record["_file"] == "batch_002.json"

        # First record should be id=15 (first record of batch_002)
        assert result["records"][0]["id"] == 15

    def test_preview_target_offset_within_second_file(self, backend_with_data):
        """Preview correctly handles offset that lands mid-file.

        With offset=18, we skip:
        - All 15 records from batch_001.json
        - First 3 records from batch_002.json (ids 15, 16, 17)
        And start at id=18.
        """
        result = backend_with_data.preview_target("extract", limit=3, offset=18)

        assert len(result["records"]) == 3
        # Should get ids 18, 19, 20
        assert result["records"][0]["id"] == 18
        assert result["records"][1]["id"] == 19
        assert result["records"][2]["id"] == 20

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

    def test_concurrent_writes_from_multiple_threads(self):
        """Concurrent writes from multiple threads don't cause transaction errors."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backend = SQLiteBackend(str(db_path), "test_workflow")
            backend.initialize()

            errors = []
            results = []

            def write_source(thread_id: int):
                try:
                    for i in range(5):
                        backend.write_source(
                            f"source_{thread_id}.json",
                            [{"source_guid": f"guid-{thread_id}-{i}", "data": f"t{thread_id}"}],
                        )
                    results.append(f"source-{thread_id}")
                except Exception as e:
                    errors.append(f"source-{thread_id}: {e}")

            def write_target(thread_id: int):
                try:
                    for i in range(5):
                        backend.write_target(
                            f"node_{thread_id}",
                            f"batch_{i}.json",
                            [{"id": i, "thread": thread_id}],
                        )
                    results.append(f"target-{thread_id}")
                except Exception as e:
                    errors.append(f"target-{thread_id}: {e}")

            # Launch multiple threads doing concurrent writes
            threads = []
            for i in range(4):
                threads.append(threading.Thread(target=write_source, args=(i,)))
                threads.append(threading.Thread(target=write_target, args=(i,)))

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            backend.close()

            # No errors should have occurred
            assert errors == [], f"Concurrent write errors: {errors}"
            assert len(results) == 8  # 4 source + 4 target threads completed


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


class TestDispositionLifecycle:
    """Test full disposition lifecycle: write -> read -> cleanup."""

    def test_passthrough_lifecycle(self):
        """Passthrough disposition can be set, queried, and cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # 1. Set passthrough disposition
                backend.set_disposition(
                    "extract", NODE_LEVEL_RECORD_ID, "passthrough", reason="All records tombstoned"
                )

                # 2. Verify it exists
                assert backend.has_disposition("extract", "passthrough") is True
                records = backend.get_disposition("extract", disposition="passthrough")
                assert len(records) == 1
                assert records[0]["reason"] == "All records tombstoned"

                # 3. Clear it
                deleted = backend.clear_disposition("extract", "passthrough")
                assert deleted == 1

                # 4. Verify it's gone
                assert backend.has_disposition("extract", "passthrough") is False

    def test_skip_disposition_lifecycle(self):
        """Skip disposition works end-to-end."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Set skip disposition
                backend.set_disposition(
                    "classify", NODE_LEVEL_RECORD_ID, "skipped", reason="WHERE clause filtered"
                )

                # Query it
                assert backend.has_disposition("classify", "skipped") is True
                records = backend.get_disposition("classify")
                assert len(records) == 1
                assert records[0]["disposition"] == "skipped"

    def test_multiple_nodes_independent(self):
        """Dispositions for different nodes are independent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                backend.set_disposition("node_a", NODE_LEVEL_RECORD_ID, "passthrough")
                backend.set_disposition("node_b", NODE_LEVEL_RECORD_ID, "skipped")

                assert backend.has_disposition("node_a", "passthrough") is True
                assert backend.has_disposition("node_a", "skipped") is False
                assert backend.has_disposition("node_b", "skipped") is True
                assert backend.has_disposition("node_b", "passthrough") is False

                # Clearing node_a doesn't affect node_b
                backend.clear_disposition("node_a")
                assert backend.has_disposition("node_b", "skipped") is True

    def test_per_record_dispositions(self):
        """Individual record dispositions work alongside node-level ones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Node-level
                backend.set_disposition("extract", NODE_LEVEL_RECORD_ID, "passthrough")

                # Per-record
                backend.set_disposition(
                    "extract", "rec_1", "exhausted", reason="Retry limit reached"
                )
                backend.set_disposition("extract", "rec_2", "filtered", reason="Below threshold")

                # Query all for node
                all_dispositions = backend.get_disposition("extract")
                assert len(all_dispositions) == 3

                # Query only exhausted
                exhausted = backend.get_disposition("extract", disposition="exhausted")
                assert len(exhausted) == 1
                assert exhausted[0]["record_id"] == "rec_1"

    def test_disposition_stats_in_storage_stats(self):
        """Storage stats include disposition count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow.db"

            with SQLiteBackend(str(db_path), "my_workflow") as backend:
                backend.initialize()

                # Write some target data and dispositions
                backend.write_target("node1", "batch.json", [{"id": 1}])
                backend.set_disposition("node1", NODE_LEVEL_RECORD_ID, "passthrough")
                backend.set_disposition("node1", "rec_1", "filtered")

                stats = backend.get_storage_stats()
                assert stats["disposition_count"] == 2
                assert stats["target_count"] == 1
