"""Tests for _prepare_json_batch handling pre-parsed content (issue #96).

FileReader._read_json() returns already-parsed Python objects (list/dict),
not raw JSON strings. _prepare_json_batch must handle both cases without
producing misleading warnings.
"""

import logging

import pytest

from agent_actions.input.preprocessing.staging.initial_pipeline import (
    _prepare_json_batch,
)


@pytest.fixture
def batch_args():
    """Common arguments for _prepare_json_batch calls."""
    return {
        "batch_id": "batch_test123",
        "node_id": "node_0_test",
        "file_path": "/tmp/test/reviews.json",
        "agent_name": "review_analyzer",
    }


class TestPrepareJsonBatchPreParsed:
    """Verify _prepare_json_batch handles pre-parsed content from FileReader."""

    def test_list_content_produces_correct_batch_rows(self, batch_args):
        """Pre-parsed list content (from FileReader._read_json) is handled directly."""
        content = [
            {"review_id": "r1", "text": "Great product"},
            {"review_id": "r2", "text": "Terrible service"},
        ]
        result = _prepare_json_batch(content, **batch_args)
        assert len(result) == 2
        assert result[0]["review_id"] == "r1"
        assert result[1]["review_id"] == "r2"
        # Batch metadata should be added
        assert "batch_id" in result[0]
        assert "target_id" in result[0]

    def test_list_content_no_warning_logged(self, batch_args, caplog):
        """Pre-parsed list content should NOT produce a JSON parse warning."""
        content = [{"id": "1", "text": "hello"}]
        with caplog.at_level(logging.WARNING):
            _prepare_json_batch(content, **batch_args)
        assert "Failed to parse JSON" not in caplog.text

    def test_dict_content_wrapped_as_single_item(self, batch_args):
        """Pre-parsed dict content is wrapped as a single-item batch."""
        content = {"review_id": "r1", "text": "Great product"}
        result = _prepare_json_batch(content, **batch_args)
        assert len(result) == 1
        # Dict content is wrapped under "content" key (not unpacked like a list)
        assert result[0]["content"]["review_id"] == "r1"
        assert "batch_id" in result[0]

    def test_string_content_parsed_as_json(self, batch_args):
        """Raw JSON string content is parsed (backward compatibility)."""
        import json

        content = json.dumps(
            [
                {"review_id": "r1", "text": "Great product"},
                {"review_id": "r2", "text": "Terrible service"},
            ]
        )
        result = _prepare_json_batch(content, **batch_args)
        assert len(result) == 2
        assert result[0]["review_id"] == "r1"

    def test_invalid_string_content_logs_warning(self, batch_args, capsys):
        """Invalid JSON string falls back with a warning."""
        content = "this is not valid json"
        _prepare_json_batch(content, **batch_args)
        captured = capsys.readouterr()
        assert "Failed to parse JSON" in captured.err

    def test_empty_list_returns_empty(self, batch_args):
        """Empty list content returns empty result."""
        result = _prepare_json_batch([], **batch_args)
        assert result == []
