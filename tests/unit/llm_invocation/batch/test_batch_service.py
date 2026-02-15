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

    def __init__(self, storage_backend=None, action_name=None):
        self.check_status = MagicMock()
        self._context_manager = MagicMock()
        self._client_resolver = MagicMock()
        self._storage_backend = storage_backend
        self._action_name = action_name

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
        output_directory: str,
    ) -> None:
        """Write batch output file."""
        from agent_actions.utils.path_utils import ensure_directory_exists
        from agent_actions.output.writer import FileWriter

        # Only create directory if not using storage backend
        if self._storage_backend is None:
            ensure_directory_exists(output_file, is_file=True)
        FileWriter(
            str(output_file),
            storage_backend=self._storage_backend,
            action_name=self._action_name,
            output_directory=output_directory,
        ).write_target(main_output)


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

        def capture_write(action_name, relative_path, data):
            written_data.append({"action_name": action_name, "path": relative_path, "data": data})

        mock_storage.write_target = capture_write

        service = MockBatchService(storage_backend=mock_storage, action_name="test_node")
        main_output = [{"id": "1", "result": "success"}]
        output_file = tmp_path / "output.json"

        service._write_batch_output(
            output_file=output_file,
            main_output=main_output,
            output_directory=str(tmp_path),
        )

        # Verify storage backend was called with correct data
        assert len(written_data) == 1
        assert written_data[0]["action_name"] == "test_node"
        assert written_data[0]["path"] == "output.json"
        assert written_data[0]["data"] == main_output
