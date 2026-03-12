"""Tests for BaseBatchClient.retrieve_results() -- regression coverage for P1-6.

The bug: `return batch_results` was indented inside the `for` loop, causing only
the first line of JSONL data to be processed when no output_directory is given.
"""

import json
from pathlib import Path
from typing import Any

from agent_actions.llm.providers.batch_base import BaseBatchClient


class StubBatchClient(BaseBatchClient):
    """Minimal concrete implementation for testing retrieve_results()."""

    def __init__(self, raw_results: bytes):
        self._raw_results = raw_results

    def _get_default_model(self) -> str:
        return "stub-model"

    def format_task_for_provider(self, batch_task, schema=None):
        return {}

    def _fetch_status(self, batch_id: str) -> str:
        return "completed"

    def _normalize_status(self, raw_status: str) -> str:
        return raw_status

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        return self._raw_results

    def _get_result_file_name(self, batch_id: str) -> str:
        return f"{batch_id}_results.jsonl"

    def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
        return Path("stub")

    def _submit_to_provider_api(self, input_file, batch_name):
        return ("stub-id", "completed")

    def _extract_error_from_response(self, raw_response: Any) -> str | None:
        return raw_response.get("error")

    def _extract_content_from_response(self, raw_response: Any) -> Any:
        return raw_response.get("content", "")

    def _extract_metadata_from_response(self, raw_response: Any) -> dict[str, Any]:
        return {}

    def _extract_usage_from_response(self, raw_response: Any) -> dict[str, Any] | None:
        return None


class TestRetrieveResultsWithoutOutputDir:
    """Regression tests for in-memory result parsing (no output_directory)."""

    def test_returns_all_results_from_multiline_jsonl(self):
        """All JSONL lines are parsed -- not just the first one."""
        results_data = [
            {"custom_id": "r1", "content": "result-1"},
            {"custom_id": "r2", "content": "result-2"},
            {"custom_id": "r3", "content": "result-3"},
        ]
        raw_bytes = "\n".join(json.dumps(r) for r in results_data).encode("utf-8")
        client = StubBatchClient(raw_bytes)

        results = client.retrieve_results("batch-123")

        assert len(results) == 3
        assert results[0].custom_id == "r1"
        assert results[1].custom_id == "r2"
        assert results[2].custom_id == "r3"
        assert all(r.success for r in results)

    def test_handles_single_line_jsonl(self):
        """Single-line JSONL still works correctly."""
        raw_bytes = json.dumps({"custom_id": "only", "content": "solo"}).encode("utf-8")
        client = StubBatchClient(raw_bytes)

        results = client.retrieve_results("batch-single")

        assert len(results) == 1
        assert results[0].custom_id == "only"

    def test_skips_blank_lines_in_jsonl(self):
        """Blank lines between JSONL records are ignored."""
        lines = [
            json.dumps({"custom_id": "a", "content": "first"}),
            "",
            json.dumps({"custom_id": "b", "content": "second"}),
            "",
        ]
        raw_bytes = "\n".join(lines).encode("utf-8")
        client = StubBatchClient(raw_bytes)

        results = client.retrieve_results("batch-blanks")

        assert len(results) == 2
        assert results[0].custom_id == "a"
        assert results[1].custom_id == "b"

    def test_malformed_json_line_produces_error_result(self):
        """A bad JSON line produces an error BatchResult instead of crashing."""
        lines = [
            json.dumps({"custom_id": "good", "content": "ok"}),
            "NOT VALID JSON{{{",
            json.dumps({"custom_id": "also_good", "content": "ok2"}),
        ]
        raw_bytes = "\n".join(lines).encode("utf-8")
        client = StubBatchClient(raw_bytes)

        results = client.retrieve_results("batch-bad")

        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert "error_line_2" == results[1].custom_id
        assert results[2].success is True
