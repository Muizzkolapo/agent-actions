"""Tests for the double-parse fix in JSON batch and online staging paths.

FileReader._read_json() returns already-parsed Python objects (via json.load()).
Previously, _prepare_json_batch() re-parsed them with json.loads(), hitting a
TypeError caught by a silent fallback. JsonLoader.process() similarly re-read
files from disk when content was already parsed.

Both bugs are now fixed:
- _prepare_json_batch() operates directly on pre-parsed content (no json.loads)
- JsonLoader.process() returns pre-parsed dict/list content directly
"""

import json
import logging
from unittest.mock import patch

from agent_actions.input.loaders.json import JsonLoader
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_batch_data,
    _prepare_json_batch,
)

# ---------------------------------------------------------------------------
# Unit tests: _prepare_json_batch()
# ---------------------------------------------------------------------------


class TestPrepareJsonBatchWithParsedInput:
    """_prepare_json_batch() receives pre-parsed objects from FileReader._read_json()."""

    def test_list_of_dicts_adds_batch_metadata(self):
        """List of dicts (common case) should get batch metadata added to each row."""
        content = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        result = _prepare_json_batch(
            content,
            batch_id="batch_test",
            node_id="node_0",
            file_path="/tmp/test.json",
            agent_name="test_agent",
        )

        assert isinstance(result, list)
        assert len(result) == 2

        # Original fields preserved
        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30
        assert result[1]["name"] == "Bob"
        assert result[1]["age"] == 25

        # Batch metadata added
        for idx, row in enumerate(result):
            assert row["batch_id"] == "batch_test"
            assert row["batch_uuid"] == f"batch_test_{idx}"
            assert "source_guid" in row
            assert "target_id" in row
            assert row["parent_target_id"] is None
            assert row["root_target_id"] == row["target_id"]
            assert row["node_id"] == "node_0"

    def test_single_dict_wrapped_in_list(self):
        """Single dict (non-list JSON) should be wrapped in a content dict."""
        content = {"key": "value", "number": 42}
        result = _prepare_json_batch(
            content,
            batch_id="batch_single",
            node_id="node_1",
            file_path="/tmp/test.json",
            agent_name="test_agent",
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["content"] == content
        assert result[0]["batch_id"] == "batch_single"
        assert result[0]["batch_uuid"] == "batch_single_0"

    def test_empty_list_returns_empty(self):
        """Empty list input should return empty list."""
        result = _prepare_json_batch(
            [],
            batch_id="batch_empty",
            node_id="node_2",
            file_path="/tmp/test.json",
            agent_name="test_agent",
        )

        assert isinstance(result, list)
        assert len(result) == 0

    def test_no_json_loads_called(self):
        """Verify json.loads is never called inside _prepare_json_batch."""
        content = [{"a": 1}]
        with patch(
            "agent_actions.input.preprocessing.staging.initial_pipeline.json.loads"
        ) as mock_loads:
            _prepare_json_batch(
                content,
                batch_id="b",
                node_id="n",
                file_path="/tmp/test.json",
                agent_name="test",
            )
            mock_loads.assert_not_called()


# ---------------------------------------------------------------------------
# Unit tests: JsonLoader.process()
# ---------------------------------------------------------------------------


class TestJsonLoaderProcessWithParsedInput:
    """JsonLoader.process() should return pre-parsed dict/list directly."""

    def test_dict_returns_directly(self):
        """Pre-parsed dict should be returned without re-parsing."""
        loader = JsonLoader({}, "test_agent")
        content = {"key": "value", "nested": {"a": 1}}
        result = loader.process(content, file_path=None)

        assert result is content  # same object, no copy/re-parse

    def test_list_returns_directly(self):
        """Pre-parsed list should be returned without re-parsing."""
        loader = JsonLoader({}, "test_agent")
        content = [{"a": 1}, {"b": 2}]
        result = loader.process(content, file_path=None)

        assert result is content  # same object, no copy/re-parse

    def test_string_content_still_parsed(self):
        """Raw JSON string should still be parsed via json.loads (BaseLoader path)."""
        loader = JsonLoader({}, "test_agent")
        json_string = '{"a": 1, "b": 2}'
        result = loader.process(json_string, file_path=None)

        assert isinstance(result, dict)
        assert result == {"a": 1, "b": 2}

    def test_file_path_still_reads_file(self, tmp_path):
        """When file_path is provided with non-parsed content, file should still be read."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"from_file": true}')

        loader = JsonLoader({}, "test_agent")
        result = loader.process(content=None, file_path=str(json_file))

        assert isinstance(result, dict)
        assert result == {"from_file": True}

    def test_dict_content_with_file_path_returns_dict_directly(self, tmp_path):
        """When content is already a dict, return it even if file_path is also provided."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"from_file": true}')

        loader = JsonLoader({}, "test_agent")
        content = {"from_memory": True}
        result = loader.process(content, file_path=str(json_file))

        # isinstance guard fires first — returns content directly, no file I/O
        assert result is content
        assert result == {"from_memory": True}


# ---------------------------------------------------------------------------
# Integration test: full pipeline path
# ---------------------------------------------------------------------------


class TestFullPipelineNoDoubleParse:
    """Integration test: FileReader.read() -> _prepare_batch_data() -> correct output."""

    def test_json_batch_pipeline_no_warnings(self, tmp_path, caplog):
        """Full pipeline from FileReader through _prepare_batch_data with JSON input.

        Verifies:
        1. No "Failed to parse JSON" warnings are logged
        2. Batch metadata is correctly added to each row
        3. Data flows through without double-parsing
        """
        # Create a real JSON file that FileReader will read
        json_data = [
            {"ticket_id": "T-001", "text": "Server is down"},
            {"ticket_id": "T-002", "text": "Cannot login"},
        ]
        json_file = tmp_path / "tickets.json"
        json_file.write_text(json.dumps(json_data))

        # Read with FileReader (returns parsed objects)
        from agent_actions.input.loaders.file_reader import FileReader

        reader = FileReader(str(json_file))
        content = reader.read()

        # Confirm FileReader returns parsed objects (not strings)
        assert isinstance(content, list)
        assert all(isinstance(item, dict) for item in content)

        # Pass through _prepare_batch_data in batch mode
        ctx = DataPreparationContext(
            content=content,
            file_type=".json",
            agent_config={"run_mode": "batch"},
            file_path=str(json_file),
            agent_name="test_agent",
            idx=0,
        )

        with caplog.at_level(logging.WARNING):
            data_chunk, src_text = _prepare_batch_data(ctx)

        # No "Failed to parse JSON" warnings should appear
        for record in caplog.records:
            assert "Failed to parse JSON" not in record.message, (
                f"Unexpected warning: {record.message}"
            )

        # Verify output structure
        assert isinstance(data_chunk, list)
        assert len(data_chunk) == 2

        # Original fields preserved with batch metadata
        assert data_chunk[0]["ticket_id"] == "T-001"
        assert data_chunk[0]["text"] == "Server is down"
        assert "batch_id" in data_chunk[0]
        assert "batch_uuid" in data_chunk[0]
        assert "source_guid" in data_chunk[0]
        assert "target_id" in data_chunk[0]

        assert data_chunk[1]["ticket_id"] == "T-002"
        assert data_chunk[1]["text"] == "Cannot login"

    def test_json_online_pipeline_with_parsed_content(self, tmp_path):
        """Online mode: JsonLoader.process() receives pre-parsed content from FileReader.

        Verifies the isinstance guard prevents redundant file re-reading.
        """
        json_data = {"ticket_id": "T-001", "text": "Server is down"}
        json_file = tmp_path / "ticket.json"
        json_file.write_text(json.dumps(json_data))

        # Read with FileReader
        from agent_actions.input.loaders.file_reader import FileReader

        reader = FileReader(str(json_file))
        content = reader.read()

        assert isinstance(content, dict)

        # Pass through JsonLoader.process() — should return directly
        loader = JsonLoader({}, "test_agent")
        result = loader.process(content, file_path=str(json_file))

        assert result is content  # same object — no re-parse, no file re-read
        assert result["ticket_id"] == "T-001"

    def test_single_dict_json_batch_pipeline(self, tmp_path, caplog):
        """Single dict JSON file flows through batch pipeline correctly."""
        json_data = {"config": "value", "setting": 42}
        json_file = tmp_path / "config.json"
        json_file.write_text(json.dumps(json_data))

        from agent_actions.input.loaders.file_reader import FileReader

        reader = FileReader(str(json_file))
        content = reader.read()

        assert isinstance(content, dict)

        ctx = DataPreparationContext(
            content=content,
            file_type=".json",
            agent_config={"run_mode": "batch"},
            file_path=str(json_file),
            agent_name="test_agent",
            idx=0,
        )

        with caplog.at_level(logging.WARNING):
            data_chunk, src_text = _prepare_batch_data(ctx)

        for record in caplog.records:
            assert "Failed to parse JSON" not in record.message

        assert isinstance(data_chunk, list)
        assert len(data_chunk) == 1
        assert data_chunk[0]["content"] == json_data
