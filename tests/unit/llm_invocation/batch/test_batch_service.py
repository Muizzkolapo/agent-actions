"""Tests for BatchService refactoring.

TDD: These tests are written BEFORE the refactoring to define
the expected behavior of extracted helper methods.

Note: Due to circular imports in the main codebase, we test the helper
methods through a minimal mock class that mimics BatchService structure.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List, Optional


# Minimal mock of BatchService for testing extracted methods
class MockBatchService:
    """Mock BatchService for testing helper methods in isolation."""

    def __init__(self, storage_backend=None, node_name=None):
        self.check_status = MagicMock()
        self._context_manager = MagicMock()
        self._client_resolver = MagicMock()
        self._storage_backend = storage_backend
        self._node_name = node_name

    def _is_batch_ready_for_processing(self, batch_id: str, output_directory: str) -> bool:
        """Check if batch is ready for processing (completed status)."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        try:
            status = self.check_status(batch_id, output_directory)
            return status == BatchStatus.COMPLETED
        except Exception:
            return False

    def _determine_output_path(
        self, output_directory: str, file_name: Optional[str], batch_id: str
    ) -> Path:
        """Determine the output file path for batch results."""
        if file_name and file_name != "default":
            return Path(output_directory) / f"{Path(file_name).stem}.json"
        return Path(output_directory) / f"{batch_id}_processed_output.json"

    def _write_batch_output(
        self,
        output_file: Path,
        main_output: List[Dict[str, Any]],
        side_output_data: Optional[List[Dict[str, Any]]],
        output_directory: str,
    ) -> None:
        """Write main and side output files."""
        from agent_actions.utils.path_utils import (
            ensure_directory_exists,
            create_side_output_directory,
        )
        from agent_actions.output.writer import FileWriter
        from agent_actions.llm.batch.processing.side_output import (
            BatchSideOutputHandler,
        )

        # Only create directory if not using storage backend
        if self._storage_backend is None:
            ensure_directory_exists(output_file, is_file=True)
        FileWriter(
            str(output_file),
            storage_backend=self._storage_backend,
            node_name=self._node_name,
            output_directory=output_directory,
        ).write_target(main_output)

        if side_output_data:
            side_output_dir = create_side_output_directory(output_directory)
            side_output_file = side_output_dir / output_file.name
            BatchSideOutputHandler.save(side_output_data, side_output_file)


class TestIsBatchReadyForProcessing:
    """Tests for _is_batch_ready_for_processing helper method."""

    def test_returns_true_when_completed(self):
        """Should return True when batch status is completed."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        service = MockBatchService()
        service.check_status = MagicMock(return_value=BatchStatus.COMPLETED)

        result = service._is_batch_ready_for_processing(
            batch_id="batch_123",
            output_directory="/tmp/test",
        )

        assert result is True

    def test_returns_false_when_in_progress(self):
        """Should return False when batch is still in progress."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        service = MockBatchService()
        service.check_status = MagicMock(return_value=BatchStatus.IN_PROGRESS)

        result = service._is_batch_ready_for_processing(
            batch_id="batch_123",
            output_directory="/tmp/test",
        )

        assert result is False

    def test_returns_false_when_failed(self):
        """Should return False when batch failed."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        service = MockBatchService()
        service.check_status = MagicMock(return_value=BatchStatus.FAILED)

        result = service._is_batch_ready_for_processing(
            batch_id="batch_123",
            output_directory="/tmp/test",
        )

        assert result is False

    def test_returns_false_on_exception(self):
        """Should return False and not raise when status check fails."""
        service = MockBatchService()
        service.check_status = MagicMock(side_effect=Exception("API error"))

        # Should not raise, should return False
        result = service._is_batch_ready_for_processing(
            batch_id="batch_123",
            output_directory="/tmp/test",
        )

        assert result is False


class TestDetermineOutputPath:
    """Tests for _determine_output_path helper method."""

    def test_uses_file_name_when_provided(self, tmp_path):
        """Should use file_name stem for output path."""
        service = MockBatchService()

        result = service._determine_output_path(
            output_directory=str(tmp_path),
            file_name="my_batch_file.jsonl",
            batch_id="batch_123",
        )

        assert result == tmp_path / "my_batch_file.json"

    def test_uses_batch_id_when_no_file_name(self, tmp_path):
        """Should use batch_id for output path when file_name is None."""
        service = MockBatchService()

        result = service._determine_output_path(
            output_directory=str(tmp_path),
            file_name=None,
            batch_id="batch_123",
        )

        assert result == tmp_path / "batch_123_processed_output.json"

    def test_uses_batch_id_when_file_name_is_default(self, tmp_path):
        """Should use batch_id for output path when file_name is 'default'."""
        service = MockBatchService()

        result = service._determine_output_path(
            output_directory=str(tmp_path),
            file_name="default",
            batch_id="batch_456",
        )

        assert result == tmp_path / "batch_456_processed_output.json"


class TestWriteBatchOutput:
    """Tests for _write_batch_output helper method."""

    def test_writes_main_output_file(self, tmp_path):
        """Should write main output to storage backend."""
        # Create mock storage backend that tracks writes
        mock_storage = MagicMock()
        written_data = []

        def capture_write(node_name, relative_path, data):
            written_data.append({"node_name": node_name, "path": relative_path, "data": data})

        mock_storage.write_target = capture_write

        service = MockBatchService(storage_backend=mock_storage, node_name="test_node")
        main_output = [{"id": "1", "result": "success"}]
        output_file = tmp_path / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            side_output_data=None,
            output_directory=str(tmp_path),
        )

        # Verify storage backend was called with correct data
        assert len(written_data) == 1
        assert written_data[0]["node_name"] == "test_node"
        assert written_data[0]["path"] == "output.json"
        assert written_data[0]["data"] == main_output

    def test_writes_side_output_when_present(self, tmp_path):
        """Should write side output to side_output directory."""
        # Create mock storage backend
        mock_storage = MagicMock()
        mock_storage.write_target = MagicMock()

        service = MockBatchService(storage_backend=mock_storage, node_name="test_node")
        main_output = [{"id": "1", "result": "success"}]
        side_output_data = [{"id": "2", "skipped": True}]

        # Create a subdirectory to match real usage pattern
        output_dir = tmp_path / "node_1_agent"
        output_dir.mkdir(parents=True)
        output_file = output_dir / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            side_output_data=side_output_data,
            output_directory=str(output_dir),
        )

        # Check storage backend was called
        mock_storage.write_target.assert_called_once()

        # Check side output directory was created (at parent level)
        side_output_dir = tmp_path / "side_output"
        assert side_output_dir.exists()

    def test_does_not_create_side_output_when_empty(self, tmp_path):
        """Should not create side_output directory when no side output."""
        # Create mock storage backend
        mock_storage = MagicMock()
        mock_storage.write_target = MagicMock()

        service = MockBatchService(storage_backend=mock_storage, node_name="test_node")
        main_output = [{"id": "1", "result": "success"}]
        output_file = tmp_path / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            side_output_data=None,
            output_directory=str(tmp_path),
        )

        # Side output directory should not be created
        side_output_dir = tmp_path / "side_output"
        assert not side_output_dir.exists()
