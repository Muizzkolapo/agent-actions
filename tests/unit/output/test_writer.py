"""Tests for FileWriter staging and target writes."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ProcessingError
from agent_actions.output.writer import FileWriter

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestFileWriterInit:
    """Tests for FileWriter initialization."""

    def test_basic_init(self, tmp_path):
        fp = str(tmp_path / "out.json")
        writer = FileWriter(fp)
        assert writer.file_path == fp
        assert writer.file_type == ".json"
        assert writer.storage_backend is None
        assert writer.action_name is None

    def test_csv_file_type(self, tmp_path):
        fp = str(tmp_path / "out.csv")
        writer = FileWriter(fp)
        assert writer.file_type == ".csv"

    def test_txt_file_type(self, tmp_path):
        fp = str(tmp_path / "out.txt")
        writer = FileWriter(fp)
        assert writer.file_type == ".txt"

    def test_with_backend_and_action_name(self, tmp_path):
        backend = MagicMock()
        fp = str(tmp_path / "out.json")
        writer = FileWriter(fp, storage_backend=backend, action_name="node_a")
        assert writer.storage_backend is backend
        assert writer.action_name == "node_a"


# ---------------------------------------------------------------------------
# JSON write_staging
# ---------------------------------------------------------------------------


class TestWriteStagingJSON:
    """Tests for write_staging with JSON files."""

    @patch("agent_actions.output.writer.fire_event")
    def test_writes_json_file(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        data = {"key": "value", "num": 42}
        writer.write_staging(data)

        with open(fp) as f:
            loaded = json.load(f)
        assert loaded == data

    @patch("agent_actions.output.writer.fire_event")
    def test_json_atomic_write(self, mock_fire, tmp_path):
        """JSON write should use atomic temp-file + rename pattern."""
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        writer.write_staging({"a": 1})

        # File should exist and be valid JSON
        assert Path(fp).exists()
        with open(fp) as f:
            assert json.load(f) == {"a": 1}

        # No leftover temp files
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    @patch("agent_actions.output.writer.fire_event")
    def test_json_creates_parent_directories(self, mock_fire, tmp_path):
        fp = str(tmp_path / "nested" / "dir" / "data.json")
        writer = FileWriter(fp)
        writer.write_staging({"x": 1})

        assert Path(fp).exists()
        with open(fp) as f:
            assert json.load(f) == {"x": 1}

    @patch("agent_actions.output.writer.fire_event")
    def test_json_indent(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        writer.write_staging({"a": 1})

        content = Path(fp).read_text()
        # json.dump with indent=4
        assert "    " in content

    @patch("agent_actions.output.writer.fire_event")
    def test_json_list_data(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        data = [{"a": 1}, {"b": 2}]
        writer.write_staging(data)

        with open(fp) as f:
            assert json.load(f) == data


# ---------------------------------------------------------------------------
# CSV write_staging
# ---------------------------------------------------------------------------


class TestWriteStagingCSV:
    """Tests for write_staging with CSV files."""

    @patch("agent_actions.output.writer.fire_event")
    def test_dict_writer_path(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.csv")
        writer = FileWriter(fp)
        data = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        writer.write_staging(data)

        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[1]["age"] == "25"

    @patch("agent_actions.output.writer.fire_event")
    def test_list_writer_path(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.csv")
        writer = FileWriter(fp)
        data = [["a", "b"], ["c", "d"]]
        writer.write_staging(data)

        with open(fp, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert rows == [["a", "b"], ["c", "d"]]

    @patch("agent_actions.output.writer.fire_event")
    def test_csv_creates_parent_dirs(self, mock_fire, tmp_path):
        fp = str(tmp_path / "sub" / "data.csv")
        writer = FileWriter(fp)
        writer.write_staging([{"x": "1"}])
        assert Path(fp).exists()


# ---------------------------------------------------------------------------
# TXT write_staging
# ---------------------------------------------------------------------------


class TestWriteStagingTXT:
    """Tests for write_staging with TXT files."""

    @patch("agent_actions.output.writer.fire_event")
    def test_list_joined_with_newlines(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.txt")
        writer = FileWriter(fp)
        writer.write_staging(["line1", "line2", "line3"])

        content = Path(fp).read_text()
        assert content == "line1\nline2\nline3"

    @patch("agent_actions.output.writer.fire_event")
    def test_string_data(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.txt")
        writer = FileWriter(fp)
        writer.write_staging("hello world")

        assert Path(fp).read_text() == "hello world"


# ---------------------------------------------------------------------------
# Unsupported file type
# ---------------------------------------------------------------------------


class TestUnsupportedFileType:
    """Tests for unsupported file types in write_staging."""

    @patch("agent_actions.output.writer.fire_event")
    def test_unsupported_extension_raises(self, mock_fire, tmp_path):
        """Unsupported file types are caught by _execute_write's error handler."""
        fp = str(tmp_path / "data.xml")
        writer = FileWriter(fp)
        # AgentActionsError is caught by handle_processing_error and re-raised
        # as ProcessingError
        with pytest.raises(ProcessingError):
            writer.write_staging({"x": 1})


# ---------------------------------------------------------------------------
# Event firing
# ---------------------------------------------------------------------------


class TestWriterEvents:
    """Tests for event firing during writes."""

    @patch("agent_actions.output.writer.fire_event")
    def test_fires_start_and_complete_events(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        writer.write_staging({"a": 1})

        assert mock_fire.call_count == 2

        start_event = mock_fire.call_args_list[0][0][0]
        assert start_event.__class__.__name__ == "FileWriteStartedEvent"
        assert start_event.file_path == fp
        assert start_event.file_type == ".json"

        complete_event = mock_fire.call_args_list[1][0][0]
        assert complete_event.__class__.__name__ == "FileWriteCompleteEvent"
        assert complete_event.file_path == fp
        assert complete_event.bytes_written > 0


# ---------------------------------------------------------------------------
# write_target
# ---------------------------------------------------------------------------


class TestWriteTarget:
    """Tests for write_target via storage backend."""

    @patch("agent_actions.output.writer.fire_event")
    def test_writes_to_backend(self, mock_fire, tmp_path):
        backend = MagicMock()
        fp = str(tmp_path / "output" / "data.json")
        writer = FileWriter(
            fp,
            storage_backend=backend,
            action_name="node_a",
            output_directory=str(tmp_path / "output"),
        )
        data = [{"result": "ok"}]
        writer.write_target(data)

        backend.write_target.assert_called_once_with("node_a", "data.json", data)

    @patch("agent_actions.output.writer.fire_event")
    def test_raises_when_no_backend(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)
        # ValueError is caught by _execute_write and re-raised through error handler
        with pytest.raises(ProcessingError):
            writer.write_target([{"x": 1}])

    @patch("agent_actions.output.writer.fire_event")
    def test_raises_when_no_action_name(self, mock_fire, tmp_path):
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp, storage_backend=MagicMock(), action_name=None)
        with pytest.raises(ProcessingError):
            writer.write_target([{"x": 1}])


# ---------------------------------------------------------------------------
# write_source
# ---------------------------------------------------------------------------


class TestWriteSource:
    """Tests for write_source (JSON atomic write)."""

    @patch("agent_actions.output.writer.fire_event")
    def test_writes_json_atomically(self, mock_fire, tmp_path):
        fp = str(tmp_path / "source.json")
        writer = FileWriter(fp)
        data = [{"id": 1}, {"id": 2}]
        writer.write_source(data)

        with open(fp) as f:
            loaded = json.load(f)
        assert loaded == data

    @patch("agent_actions.output.writer.fire_event")
    def test_creates_parent_dirs(self, mock_fire, tmp_path):
        fp = str(tmp_path / "deep" / "nested" / "source.json")
        writer = FileWriter(fp)
        writer.write_source({"k": "v"})

        assert Path(fp).exists()

    @patch("agent_actions.output.writer.fire_event")
    def test_no_leftover_tmp_files(self, mock_fire, tmp_path):
        fp = str(tmp_path / "source.json")
        writer = FileWriter(fp)
        writer.write_source({"k": "v"})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# Error handling in _execute_write
# ---------------------------------------------------------------------------


class TestExecuteWriteErrors:
    """Tests for error handling in _execute_write."""

    @patch("agent_actions.output.writer.fire_event")
    def test_os_error_handled(self, mock_fire, tmp_path):
        """OSError in the write function triggers handle_file_error."""
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)

        # Make the parent dir read-only to trigger an OSError
        # Instead, we mock the inner write function
        with patch.object(writer, "handle_file_error") as mock_handler:
            mock_handler.side_effect = Exception("handled")
            # Trigger an OSError by patching Path.mkdir to raise
            with patch("agent_actions.output.writer.Path.mkdir", side_effect=OSError("denied")):
                with pytest.raises(Exception, match="handled"):
                    writer.write_staging({"x": 1})
            mock_handler.assert_called_once()

    @patch("agent_actions.output.writer.fire_event")
    def test_non_os_error_handled(self, mock_fire, tmp_path):
        """Non-OSError exceptions trigger handle_processing_error."""
        fp = str(tmp_path / "data.json")
        writer = FileWriter(fp)

        with patch.object(writer, "handle_processing_error") as mock_handler:
            mock_handler.side_effect = Exception("handled")
            # json.dump will fail on non-serializable data
            with patch("agent_actions.output.writer.json.dump", side_effect=TypeError("bad")):
                with pytest.raises(Exception, match="handled"):
                    writer.write_staging({"x": 1})
            mock_handler.assert_called_once()
