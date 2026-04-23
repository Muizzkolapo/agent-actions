"""Tests for storage-backend-aware output reading.

Verifies that _process_agent_output reads from backend before falling back
to filesystem.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.output import (
    ActionOutputManager,
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
    """Factory that builds an ActionOutputManager with sensible defaults."""

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
        return ActionOutputManager(config)

    return _make


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
