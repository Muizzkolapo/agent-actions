"""Tests for record merge behavior."""

from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.merge import merge_records_by_key
from agent_actions.workflow.runner import ActionRunner


class TestMergeRecordsByKey:
    """Tests for merge_records_by_key function."""

    def test_merges_records_with_same_source_guid(self):
        """Should merge records with the same source_guid."""
        records = [
            {"source_guid": "abc123", "field_1": "value_1"},
            {"source_guid": "abc123", "field_2": "value_2"},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        assert result[0]["source_guid"] == "abc123"
        assert result[0]["field_1"] == "value_1"
        assert result[0]["field_2"] == "value_2"

    def test_merges_records_with_parent_target_id(self):
        """Should merge records using parent_target_id when reduce_key is set."""
        records = [
            {"parent_target_id": "xyz", "answer_1": "A"},
            {"parent_target_id": "xyz", "answer_2": "B"},
        ]

        result = merge_records_by_key(records, reduce_key="parent_target_id")

        assert len(result) == 1
        assert result[0]["answer_1"] == "A"
        assert result[0]["answer_2"] == "B"

    def test_uses_explicit_reduce_key(self):
        """Should use explicit reduce_key when provided."""
        records = [
            {"custom_id": "123", "source_guid": "different1", "data": "a"},
            {"custom_id": "123", "source_guid": "different2", "data": "b"},
        ]

        result = merge_records_by_key(records, reduce_key="custom_id")

        assert len(result) == 1
        assert result[0]["custom_id"] == "123"

    def test_keeps_separate_records_with_different_keys(self):
        """Should keep records separate when they have different correlation keys."""
        records = [
            {"source_guid": "abc", "value": 1},
            {"source_guid": "xyz", "value": 2},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2

    def test_handles_records_without_correlation_key(self):
        """Should include records without correlation keys as-is."""
        records = [
            {"source_guid": "abc", "merged": True},
            {"no_key": "orphan"},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 2

    def test_handles_non_dict_records(self):
        """Should handle non-dict records gracefully."""
        records = [
            {"source_guid": "abc", "value": 1},
            "string_record",
            123,
        ]

        result = merge_records_by_key(records)

        assert len(result) == 3

    def test_merges_content_deeply(self):
        """Should deep merge content dictionaries."""
        records = [
            {"source_guid": "abc", "content": {"field_a": "A"}},
            {"source_guid": "abc", "content": {"field_b": "B"}},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        assert result[0]["content"]["field_a"] == "A"
        assert result[0]["content"]["field_b"] == "B"

    def test_merges_lineage_with_deduplication(self):
        """Should merge lineage arrays with deduplication."""
        records = [
            {"source_guid": "abc", "lineage": ["node_1", "node_2"]},
            {"source_guid": "abc", "lineage": ["node_2", "node_3"]},
        ]

        result = merge_records_by_key(records)

        assert len(result) == 1
        lineage = result[0]["lineage"]
        assert len(lineage) == 3
        assert set(lineage) == {"node_1", "node_2", "node_3"}


class TestStorageBackendMerge:
    """Tests for merge behavior in _process_from_storage_backend."""

    @pytest.fixture
    def runner(self):
        """Create an ActionRunner instance with mocked storage backend."""
        runner = ActionRunner.__new__(ActionRunner)
        runner.storage_backend = MagicMock()
        runner.console = MagicMock()
        return runner

    def test_merges_data_from_parallel_branches(self, runner):
        """Should merge data when same file exists in multiple upstream nodes."""
        # Setup: Two upstream nodes with same relative path
        runner.storage_backend.list_target_files.side_effect = [
            ["data.json"],  # node_1
            ["data.json"],  # node_2
        ]
        runner.storage_backend.read_target.side_effect = [
            [{"source_guid": "abc", "field_1": "A"}],  # node_1/data.json
            [{"source_guid": "abc", "field_2": "B"}],  # node_2/data.json
        ]

        # Mock _process_single_file to capture the processed data
        processed_data = []

        def capture_process(params):
            # Data is now passed directly via params.data (no temp file)
            assert params.data is not None, "params.data should be populated"
            processed_data.append(params.data)

        runner._process_single_file = capture_process

        # Create params
        params = MagicMock()
        params.upstream_data_dirs = ["/target/node_1", "/target/node_2"]
        params.output_directory = "/output"
        params.action_config = {}
        params.agent_name = "test_agent"
        params.strategy = MagicMock()
        params.idx = 0

        # Execute
        files_found, files_processed = runner._process_from_storage_backend(params)

        # Verify merge happened
        assert files_found == 1  # One unique path
        assert files_processed == 1
        assert len(processed_data) == 1

        merged = processed_data[0]
        assert len(merged) == 1  # One merged record
        assert merged[0]["field_1"] == "A"
        assert merged[0]["field_2"] == "B"

    def test_processes_unique_files_independently(self, runner):
        """Should process files with unique paths independently."""
        runner.storage_backend.list_target_files.side_effect = [
            ["file_a.json"],  # node_1
            ["file_b.json"],  # node_2
        ]
        runner.storage_backend.read_target.side_effect = [
            [{"data": "a"}],
            [{"data": "b"}],
        ]

        processed_data = []

        def capture_process(params):
            # Data is now passed directly via params.data (no temp file)
            assert params.data is not None, "params.data should be populated"
            processed_data.append(params.data)

        runner._process_single_file = capture_process

        params = MagicMock()
        params.upstream_data_dirs = ["/target/node_1", "/target/node_2"]
        params.output_directory = "/output"
        params.action_config = {}
        params.agent_name = "test_agent"
        params.strategy = MagicMock()
        params.idx = 0

        files_found, files_processed = runner._process_from_storage_backend(params)

        # Two unique files processed
        assert files_found == 2
        assert files_processed == 2
        assert len(processed_data) == 2

    def test_preserves_subdirectory_in_source_relative_path(self, runner):
        """Should preserve subdirectory structure in source_relative_path for strategy."""
        # Setup: File with subdirectory path
        runner.storage_backend.list_target_files.side_effect = [
            ["subdir/nested/file.json"],  # node_1
        ]
        runner.storage_backend.read_target.side_effect = [
            [{"data": "value"}],
        ]

        # Capture the source_relative_path passed to strategy
        captured_params = []

        def capture_process(params):
            captured_params.append(params)

        runner._process_single_file = capture_process

        params = MagicMock()
        params.upstream_data_dirs = ["/target/node_1"]
        params.output_directory = "/output"
        params.action_config = {}
        params.agent_name = "test_agent"
        params.strategy = MagicMock()
        params.idx = 0

        runner._process_from_storage_backend(params)

        # Verify source_relative_path preserves full path without extension
        assert len(captured_params) == 1
        assert captured_params[0].source_relative_path == "subdir/nested/file"
