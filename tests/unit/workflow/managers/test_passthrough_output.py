"""Tests for storage-backend-aware passthrough and output reading.

Verifies that create_passthrough_output reads from backend (with filesystem
fallback) and writes to backend, and that _process_agent_output reads from
backend before falling back to filesystem.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.output import (
    AgentOutputManager,
    OutputManagerConfig,
)


@pytest.fixture
def mock_storage_backend():
    backend = MagicMock()
    backend.list_target_files.return_value = []
    backend.get_disposition.return_value = []
    return backend


@pytest.fixture
def make_manager(tmp_path, mock_storage_backend):
    """Factory that builds an AgentOutputManager with sensible defaults."""

    def _make(
        execution_order=None,
        action_configs=None,
        action_status=None,
        storage_backend=None,
    ):
        config = OutputManagerConfig(
            agent_folder=tmp_path,
            execution_order=execution_order or ["extract", "transform"],
            action_configs=action_configs or {},
            action_status=action_status or {},
            version_correlator=MagicMock(),
            storage_backend=storage_backend or mock_storage_backend,
        )
        return AgentOutputManager(config)

    return _make


# ---------------------------------------------------------------------------
# create_passthrough_output — backend has upstream data
# ---------------------------------------------------------------------------


class TestPassthroughFromBackend:
    def test_reads_backend_writes_backend(self, make_manager, mock_storage_backend):
        """When backend has upstream data, reads and writes through backend."""
        upstream_data = [{"id": "1", "val": "a"}, {"id": "2", "val": "b"}]
        mock_storage_backend.list_target_files.return_value = ["batch_0.json"]
        mock_storage_backend.read_target.return_value = upstream_data

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_configs={"transform": {}},
        )
        mgr.create_passthrough_output(1, "transform")

        # Should have read from upstream node "extract"
        mock_storage_backend.list_target_files.assert_called_with("extract")
        mock_storage_backend.read_target.assert_called_with("extract", "batch_0.json")

        # Should have written to the skipped node "transform"
        mock_storage_backend.write_target.assert_called_once_with(
            "transform", "batch_0.json", upstream_data
        )

        # Disposition recorded
        mock_storage_backend.set_disposition.assert_called_once()
        call_args = mock_storage_backend.set_disposition.call_args
        assert call_args[0][0] == "transform"
        assert call_args[0][2] == "skipped"

    def test_multiple_backend_files(self, make_manager, mock_storage_backend):
        """All files from upstream node are forwarded."""
        mock_storage_backend.list_target_files.return_value = [
            "batch_0.json",
            "batch_1.json",
        ]
        mock_storage_backend.read_target.side_effect = [
            [{"id": "1"}],
            [{"id": "2"}],
        ]

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_configs={"transform": {}},
        )
        mgr.create_passthrough_output(1, "transform")

        assert mock_storage_backend.write_target.call_count == 2

    def test_parallel_branches_merge(self, tmp_path, make_manager, mock_storage_backend):
        """When same file exists in two upstream branches, records merge by reduce_key."""
        # Two upstream branches each have batch_0.json with same-keyed records
        mock_storage_backend.list_target_files.return_value = ["batch_0.json"]
        mock_storage_backend.read_target.side_effect = [
            [{"parent_target_id": "x", "answer_1": "A"}],
            [{"parent_target_id": "x", "answer_2": "B"}],
        ]

        mgr = make_manager(
            execution_order=["branch_a", "branch_b", "merge_node"],
            action_configs={
                "merge_node": {
                    "dependencies": ["branch_a", "branch_b"],
                    "reduce_key": "parent_target_id",
                },
            },
        )
        # Paths must be under target/ so backend is queried
        branch_a = str(tmp_path / "target" / "branch_a")
        branch_b = str(tmp_path / "target" / "branch_b")
        with patch.object(mgr, "get_upstream_directories", return_value=[branch_a, branch_b]):
            mgr.create_passthrough_output(2, "merge_node")

        # Should have written merged data
        mock_storage_backend.write_target.assert_called_once()
        written_data = mock_storage_backend.write_target.call_args[0][2]
        assert len(written_data) == 1
        assert written_data[0]["parent_target_id"] == "x"
        assert written_data[0]["answer_1"] == "A"
        assert written_data[0]["answer_2"] == "B"


# ---------------------------------------------------------------------------
# create_passthrough_output — filesystem fallback
# ---------------------------------------------------------------------------


class TestPassthroughFromFilesystem:
    def test_falls_back_to_filesystem(self, tmp_path, make_manager, mock_storage_backend):
        """When backend has no data, reads from filesystem and writes to backend."""
        # Backend returns nothing
        mock_storage_backend.list_target_files.return_value = []

        # Set up filesystem data
        extract_dir = tmp_path / "target" / "extract"
        extract_dir.mkdir(parents=True)
        records = [{"id": "1", "val": "fs"}]
        (extract_dir / "batch_0.json").write_text(json.dumps(records))

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_configs={"transform": {}},
        )
        mgr.create_passthrough_output(1, "transform")

        # Should write filesystem data to backend
        mock_storage_backend.write_target.assert_called_once_with(
            "transform", "batch_0.json", records
        )

    def test_skips_non_json_files(self, tmp_path, make_manager, mock_storage_backend):
        """Non-JSON files on filesystem are ignored."""
        mock_storage_backend.list_target_files.return_value = []

        extract_dir = tmp_path / "target" / "extract"
        extract_dir.mkdir(parents=True)
        (extract_dir / "readme.txt").write_text("not json")
        (extract_dir / "batch_0.json").write_text(json.dumps([{"id": "1"}]))

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_configs={"transform": {}},
        )
        mgr.create_passthrough_output(1, "transform")

        # Only the JSON file should be written
        mock_storage_backend.write_target.assert_called_once()
        assert mock_storage_backend.write_target.call_args[0][1] == "batch_0.json"

    def test_empty_upstream_writes_nothing(self, make_manager, mock_storage_backend):
        """No upstream data → no writes, but disposition is still recorded."""
        mock_storage_backend.list_target_files.return_value = []

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_configs={"transform": {}},
        )
        mgr.create_passthrough_output(1, "transform")

        mock_storage_backend.write_target.assert_not_called()
        mock_storage_backend.set_disposition.assert_called_once()


# ---------------------------------------------------------------------------
# create_passthrough_output — start-node paths skip backend
# ---------------------------------------------------------------------------


class TestPassthroughStartNode:
    def test_staging_dir_skips_backend(self, tmp_path, make_manager, mock_storage_backend):
        """Start-node paths (staging/) go straight to filesystem, never query backend."""
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        (staging_dir / "input.json").write_text(json.dumps([{"id": "1"}]))

        mgr = make_manager(
            execution_order=["extract"],
            action_configs={"extract": {}},
        )
        with patch.object(mgr, "get_upstream_directories", return_value=[str(staging_dir)]):
            mgr.create_passthrough_output(0, "extract")

        # Backend should NOT have been queried with "staging" as node name
        mock_storage_backend.list_target_files.assert_not_called()
        # Data should still be written to backend from filesystem
        mock_storage_backend.write_target.assert_called_once_with(
            "extract", "input.json", [{"id": "1"}]
        )

    def test_non_target_path_skips_backend(self, tmp_path, make_manager, mock_storage_backend):
        """Arbitrary non-target paths (local data source) skip backend lookup."""
        data_dir = tmp_path / "external_data"
        data_dir.mkdir()
        (data_dir / "records.json").write_text(json.dumps([{"k": "v"}]))

        mgr = make_manager(
            execution_order=["ingest"],
            action_configs={"ingest": {}},
        )
        with patch.object(mgr, "get_upstream_directories", return_value=[str(data_dir)]):
            mgr.create_passthrough_output(0, "ingest")

        mock_storage_backend.list_target_files.assert_not_called()
        mock_storage_backend.write_target.assert_called_once()


# ---------------------------------------------------------------------------
# _process_agent_output — backend read with filesystem fallback
# ---------------------------------------------------------------------------


class TestProcessAgentOutputBackend:
    def test_backend_data_returned(self, tmp_path, make_manager, mock_storage_backend):
        """When backend has data, returns it without touching filesystem."""
        mock_storage_backend.list_target_files.return_value = ["batch_0.json"]
        mock_storage_backend.read_target.return_value = [
            {"id": "1", "val": "from_backend"},
        ]

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        output_dir = tmp_path / "target" / "extract"
        result = mgr._process_agent_output(output_dir, "extract")

        assert result["has_data"] is True
        assert result["output_count"] == 1
        assert result["data"][0]["val"] == "from_backend"

    def test_output_files_populated_from_backend(
        self, tmp_path, make_manager, mock_storage_backend
    ):
        """output_files is populated even when data comes from backend."""
        mock_storage_backend.list_target_files.return_value = [
            "batch_0.json",
            "batch_1.json",
        ]
        mock_storage_backend.read_target.side_effect = [
            [{"id": "1"}],
            [{"id": "2"}],
        ]

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        output_dir = tmp_path / "target" / "extract"
        result = mgr._process_agent_output(output_dir, "extract")

        assert result["output_files"] == ["batch_0.json", "batch_1.json"]
        assert result["output_count"] == 2

    def test_falls_back_to_filesystem(self, tmp_path, make_manager, mock_storage_backend):
        """When backend has no data, falls back to filesystem glob."""
        mock_storage_backend.list_target_files.return_value = []

        output_dir = tmp_path / "target" / "extract"
        output_dir.mkdir(parents=True)
        (output_dir / "batch_0.json").write_text(json.dumps([{"id": "1", "val": "from_fs"}]))

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        result = mgr._process_agent_output(output_dir, "extract")

        assert result["has_data"] is True
        assert result["data"][0]["val"] == "from_fs"
        assert "batch_0.json" in result["output_files"]

    def test_both_empty_returns_empty(self, tmp_path, make_manager, mock_storage_backend):
        """When both backend and filesystem have no data, returns empty output."""
        mock_storage_backend.list_target_files.return_value = []

        output_dir = tmp_path / "target" / "extract"
        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        result = mgr._process_agent_output(output_dir, "extract")

        assert result["has_data"] is False
        assert result["output_count"] == 0
        assert result["data"] == []

    def test_disposition_queries_filter_by_node_level_record_id(
        self, tmp_path, make_manager, mock_storage_backend
    ):
        """Disposition queries must filter by NODE_LEVEL_RECORD_ID to avoid picking up per-record rows."""
        mock_storage_backend.list_target_files.return_value = []
        mock_storage_backend.get_disposition.return_value = []

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        output_dir = tmp_path / "target" / "extract"
        mgr._process_agent_output(output_dir, "extract")

        # Both disposition calls must include record_id=NODE_LEVEL_RECORD_ID
        disposition_calls = mock_storage_backend.get_disposition.call_args_list
        assert len(disposition_calls) == 2
        for c in disposition_calls:
            assert c.kwargs.get("record_id") == NODE_LEVEL_RECORD_ID

    def test_backend_exception_falls_back(self, tmp_path, make_manager, mock_storage_backend):
        """When backend raises an exception, falls back to filesystem."""
        mock_storage_backend.list_target_files.side_effect = RuntimeError("db locked")

        output_dir = tmp_path / "target" / "extract"
        output_dir.mkdir(parents=True)
        (output_dir / "batch_0.json").write_text(json.dumps([{"id": "1", "val": "fallback"}]))

        mgr = make_manager(
            execution_order=["extract", "transform"],
            action_status={"extract": {"status": "completed"}},
        )
        result = mgr._process_agent_output(output_dir, "extract")

        assert result["has_data"] is True
        assert result["data"][0]["val"] == "fallback"


# ---------------------------------------------------------------------------
# C-2  ·  get_upstream_directories — guard dep_index < 0
# ---------------------------------------------------------------------------


class TestGetUpstreamDirectoriesGuard:
    """C-2 — idx=0 with no resolvable upstream raises ConfigurationError."""

    def test_idx_zero_with_deps_that_dont_exist_raises(self, make_manager, tmp_path):
        """When idx=0 has dependencies but none resolve, ConfigurationError is raised."""
        mgr = make_manager(
            execution_order=["first", "second"],
            action_configs={"first": {"dependencies": ["nonexistent_dep"]}},
        )
        # version_correlator returns empty map so we fall through to the guard
        mgr.version_correlator.detect_explicit_version_consumption.return_value = {}

        with pytest.raises(ConfigurationError, match="declared dependencies that could not be resolved"):
            mgr.get_upstream_directories(0)

    def test_idx_one_returns_correct_upstream_path(self, make_manager, tmp_path):
        """idx=1 with no explicit deps falls through to the previous-agent path."""
        mgr = make_manager(
            execution_order=["first", "second"],
            action_configs={"second": {}},
        )
        mgr.version_correlator.detect_explicit_version_consumption.return_value = {}

        result = mgr.get_upstream_directories(1)
        assert len(result) == 1
        assert result[0].endswith("first")
