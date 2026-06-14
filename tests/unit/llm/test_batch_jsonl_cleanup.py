"""Tests for batch JSONL file cleanup after upload and retrieval.

Verifies that input JSONL files are deleted after successful provider upload
and result JSONL files are deleted after successful parsing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agent_actions.llm.providers.batch_base import BaseBatchClient


class _StubBatchClient(BaseBatchClient):
    """Minimal concrete implementation for testing base class cleanup."""

    vendor_type = "stub"

    def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "stub")

    def _submit_to_provider_api(self, input_file, batch_name):
        return ("batch_123", "validating")

    def _fetch_status(self, batch_id):
        return "completed"

    def _normalize_status(self, raw_status):
        return raw_status

    def _fetch_raw_results(self, batch_id):
        result = {
            "custom_id": "id1",
            "response": {"body": {"choices": [{"message": {"content": '"hello"'}}]}},
        }
        return (json.dumps(result) + "\n").encode()

    def _parse_result(self, raw_result):
        from agent_actions.llm.providers.batch_base import BatchResult

        return BatchResult(
            custom_id=raw_result.get("custom_id", "unknown"),
            content="hello",
            success=True,
        )

    def _get_result_file_name(self, batch_id):
        return f"{batch_id}_results.jsonl"

    def _get_default_model(self):
        return "stub-model"

    def format_task_for_provider(self, *args, **kwargs):
        return {}

    def _extract_content_from_response(self, response):
        return response

    def _extract_error_from_response(self, response):
        return None

    def _extract_metadata_from_response(self, response):
        return {}

    def _extract_usage_from_response(self, response):
        return {}


class TestInputJsonlCleanup:
    """Input JSONL file must be deleted after successful provider upload."""

    def test_input_file_deleted_after_submit(self, tmp_path: Path):
        client = _StubBatchClient()
        output_dir = str(tmp_path / "agent_io" / "target" / "extract")

        client.submit_batch(
            tasks=[{"custom_id": "1", "body": {}}],
            batch_name="extract",
            output_directory=output_dir,
        )

        batch_dir = tmp_path / "agent_io" / "target" / "extract" / "batch"
        jsonl_files = list(batch_dir.glob("*_batch_input.jsonl"))
        assert jsonl_files == [], f"Input JSONL not cleaned up: {jsonl_files}"

    def test_input_file_created_then_deleted(self, tmp_path: Path):
        """Verify the file IS created during submission (not skipped entirely)."""
        created_files: list[Path] = []
        original_submit = _StubBatchClient._submit_to_provider_api

        def spy_submit(self, input_file, batch_name):
            created_files.append(input_file)
            assert input_file.exists(), "Input file should exist before upload"
            return original_submit(self, input_file, batch_name)

        client = _StubBatchClient()
        output_dir = str(tmp_path / "agent_io" / "target" / "extract")

        with patch.object(_StubBatchClient, "_submit_to_provider_api", spy_submit):
            client.submit_batch(
                tasks=[{"custom_id": "1", "body": {}}],
                batch_name="extract",
                output_directory=output_dir,
            )

        assert len(created_files) == 1
        assert not created_files[0].exists(), "Input file should be deleted after upload"


class TestResultJsonlCleanup:
    """Result JSONL file must be deleted after successful parsing."""

    def test_result_file_deleted_after_retrieve(self, tmp_path: Path):
        client = _StubBatchClient()
        output_dir = str(tmp_path / "agent_io" / "target" / "extract")
        (tmp_path / "agent_io" / "target" / "extract" / "batch").mkdir(parents=True)

        results = client.retrieve_results("batch_123", output_dir)

        assert len(results) == 1
        batch_dir = tmp_path / "agent_io" / "target" / "extract" / "batch"
        jsonl_files = list(batch_dir.glob("*_results.jsonl"))
        assert jsonl_files == [], f"Result JSONL not cleaned up: {jsonl_files}"

    def test_retrieve_without_output_dir_skips_file_write(self):
        """When no output_directory, results parsed from memory — no file to clean."""
        client = _StubBatchClient()
        results = client.retrieve_results("batch_123")
        assert len(results) == 1
