"""Tests that JSON content flows through the staging pipeline without redundant parsing.

Covers:
- _prepare_json_batch() accepting pre-parsed dicts/lists
- JsonLoader.process() short-circuiting on already-parsed content
- Full pipeline integration from FileReader through _prepare_batch_data()
"""

import json
import logging

from agent_actions.input.loaders.file_reader import FileReader
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
    """_prepare_json_batch() receives pre-parsed objects, not JSON strings."""

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

        assert result == []


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

        assert result is content

    def test_list_returns_directly(self):
        """Pre-parsed list should be returned without re-parsing."""
        loader = JsonLoader({}, "test_agent")
        content = [{"a": 1}, {"b": 2}]
        result = loader.process(content, file_path=None)

        assert result is content

    def test_string_content_still_parsed(self):
        """Raw JSON string should still be parsed via json.loads (BaseLoader path)."""
        loader = JsonLoader({}, "test_agent")
        json_string = '{"a": 1, "b": 2}'
        result = loader.process(json_string, file_path=None)

        assert result == {"a": 1, "b": 2}

    def test_file_path_still_reads_file(self, tmp_path):
        """When file_path is provided with non-parsed content, file should still be read."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"from_file": true}')

        loader = JsonLoader({}, "test_agent")
        result = loader.process(content=None, file_path=str(json_file))

        assert result == {"from_file": True}

    def test_dict_content_with_file_path_returns_dict_directly(self, tmp_path):
        """When content is already a dict, return it even if file_path is also provided."""
        json_file = tmp_path / "test.json"
        json_file.write_text('{"from_file": true}')

        loader = JsonLoader({}, "test_agent")
        content = {"from_memory": True}
        result = loader.process(content, file_path=str(json_file))

        assert result is content


# ---------------------------------------------------------------------------
# Integration test: full pipeline path
# ---------------------------------------------------------------------------


class TestFullPipelineNoDoubleParse:
    """Integration: FileReader.read() -> _prepare_batch_data() -> correct output."""

    def test_json_batch_pipeline_no_warnings(self, tmp_path, caplog):
        """Full pipeline from FileReader through _prepare_batch_data with JSON input."""
        json_data = [
            {"ticket_id": "T-001", "text": "Server is down"},
            {"ticket_id": "T-002", "text": "Cannot login"},
        ]
        json_file = tmp_path / "tickets.json"
        json_file.write_text(json.dumps(json_data))

        reader = FileReader(str(json_file))
        content = reader.read()

        assert isinstance(content, list)

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
            assert "Failed to parse JSON" not in record.message, (
                f"Unexpected warning: {record.message}"
            )

        assert len(data_chunk) == 2
        assert data_chunk[0]["ticket_id"] == "T-001"
        assert "batch_id" in data_chunk[0]
        assert "source_guid" in data_chunk[0]
        assert data_chunk[1]["ticket_id"] == "T-002"

    def test_json_online_pipeline_with_parsed_content(self, tmp_path):
        """Online mode: JsonLoader.process() returns pre-parsed content directly."""
        json_data = {"ticket_id": "T-001", "text": "Server is down"}
        json_file = tmp_path / "ticket.json"
        json_file.write_text(json.dumps(json_data))

        reader = FileReader(str(json_file))
        content = reader.read()

        loader = JsonLoader({}, "test_agent")
        result = loader.process(content, file_path=str(json_file))

        assert result is content
        assert result["ticket_id"] == "T-001"
