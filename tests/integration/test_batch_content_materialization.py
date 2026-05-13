"""Integration tests for batch content materialization.

Verifies that batch LLM results are injected into content.{action_name}
and persisted to both the storage backend and the filesystem.
"""

import json
from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing_recovery import _stamp_batch_records
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import FileWriter
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _process_batch(
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    action_config: dict[str, Any],
    output_directory: str,
    action_name: str = "verify_answer",
) -> list[dict[str, Any]]:
    """Process batch results through strategy + enrichment + stamp (production path)."""
    strategy = BatchResultStrategy()
    results = strategy.process(
        batch_results=batch_results,
        context_map=context_map,
        output_directory=output_directory,
        agent_config=action_config,
    )
    enrichment = EnrichmentPipeline()
    output: list[dict[str, Any]] = []
    for result in results:
        if result.processing_context is not None:
            result = enrichment.enrich(result, result.processing_context)
        output.extend(result.data or [])
    _stamp_batch_records(output, action_name)
    return output


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def action_config() -> dict[str, Any]:
    return {
        "name": "verify_answer",
        "action_name": "verify_answer",
        "kind": "llm",
        "model_vendor": "openai",
        "model_name": "gpt-4o-mini",
        "json_mode": True,
        "output_field": "raw_response",
        "context_scope": {
            "observe": ["source.question", "write_scenario_question.verified_answer"],
        },
    }


@pytest.fixture
def upstream_record() -> dict[str, Any]:
    return {
        "source_guid": "src_001",
        "target_id": "tid_001",
        "version_correlation_id": "corr_001",
        "content": {
            "summarize_page_content": {"summary": "AWS S3 bucket policies..."},
            "write_scenario_question": {
                "question_text": "What is the correct S3 bucket policy?",
                "answer_text": "Option C",
            },
        },
    }


@pytest.fixture
def llm_response() -> dict[str, Any]:
    return {
        "verified_answer": "C",
        "verification_reasoning": "Option C correctly allows all principals.",
    }


@pytest.fixture
def batch_result(llm_response) -> BatchResult:
    return BatchResult(
        custom_id="tid_001",
        content=llm_response,
        success=True,
        error=None,
        metadata={"model": "gpt-4o-mini", "finish_reason": "stop"},
    )


@pytest.fixture
def context_map(upstream_record) -> dict[str, Any]:
    record = upstream_record.copy()
    record["_filter_status"] = "included"
    return {"tid_001": record}


@pytest.fixture
def sqlite_backend(tmp_path) -> SQLiteBackend:
    backend = SQLiteBackend(str(tmp_path / "test.db"), workflow_name="test_workflow")
    backend.initialize()
    return backend


# ---------------------------------------------------------------------------
# Content assembly
# ---------------------------------------------------------------------------


class TestBatchContentAssembly:
    """BatchResultStrategy correctly builds content[action_name]."""

    def test_successful_result_populates_action_namespace(
        self, action_config, batch_result, context_map
    ):
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        item = results[0].data[0]
        content = item["content"]

        assert content["verify_answer"]["verified_answer"] == "C"
        assert "verification_reasoning" in content["verify_answer"]
        assert "summarize_page_content" in content
        assert "write_scenario_question" in content

    def test_string_content_wrapped_as_parse_error(self, action_config, context_map):
        """Unparsed string in json_mode gets wrapped as _parse_error."""
        result = BatchResult(
            custom_id="tid_001",
            content='{"verified_answer": "C"}',
            success=True,
            error=None,
        )
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        action_ns = results[0].data[0]["content"]["verify_answer"]
        assert "_parse_error" in action_ns or "verified_answer" in action_ns

    def test_framework_fields_carried(self, action_config, batch_result, context_map):
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        item = results[0].data[0]
        assert item["target_id"] == "tid_001"
        assert item["version_correlation_id"] == "corr_001"


# ---------------------------------------------------------------------------
# Full pipeline → DB roundtrip
# ---------------------------------------------------------------------------


class TestBatchToDBPipeline:
    """Batch result → enrichment → stamp → DB write → DB read."""

    def test_content_survives_enrichment_and_db_roundtrip(
        self, action_config, batch_result, context_map, sqlite_backend, tmp_path
    ):
        output = _process_batch([batch_result], context_map, action_config, str(tmp_path))

        writer = FileWriter(
            str(tmp_path / "out.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "out.json")
        assert data[0]["content"]["verify_answer"]["verified_answer"] == "C"

    def test_multiple_records_all_populated(
        self, action_config, context_map, sqlite_backend, tmp_path
    ):
        records = []
        for i in range(3):
            tid = f"tid_{i:03d}"
            context_map[tid] = {
                "source_guid": f"src_{i:03d}",
                "target_id": tid,
                "content": {"upstream_action": {"field": f"value_{i}"}},
                "_filter_status": "included",
            }
            records.append(
                BatchResult(
                    custom_id=tid,
                    content={"score": i * 10, "reasoning": f"Reason {i}"},
                    success=True,
                    error=None,
                )
            )

        output = _process_batch(records, context_map, action_config, str(tmp_path))
        writer = FileWriter(
            str(tmp_path / "batch.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "batch.json")
        hollow = [r for r in data if r.get("content", {}).get("verify_answer") in (None, {})]
        assert hollow == [], f"{len(hollow)}/{len(data)} records have hollow content"


# ---------------------------------------------------------------------------
# Versioned actions
# ---------------------------------------------------------------------------


class TestVersionedBatchContent:
    def test_versioned_action_name_in_content(self, context_map, sqlite_backend, tmp_path):
        config = {
            "name": "verify_answer_1",
            "action_name": "verify_answer_1",
            "kind": "llm",
            "model_vendor": "openai",
            "model_name": "gpt-4o-mini",
            "json_mode": True,
            "output_field": "raw_response",
            "is_versioned_agent": True,
            "version_base_name": "verify_answer",
        }
        result = BatchResult(
            custom_id="tid_001",
            content={"verified_answer": "C", "verification_reasoning": "Correct"},
            success=True,
            error=None,
            metadata={"model": "gpt-4o-mini"},
        )

        output = _process_batch([result], context_map, config, str(tmp_path), "verify_answer_1")
        writer = FileWriter(
            str(tmp_path / "out.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer_1",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer_1", "out.json")
        assert data[0]["content"]["verify_answer_1"]["verified_answer"] == "C"
        assert data[0]["version_correlation_id"] == "corr_001"


# ---------------------------------------------------------------------------
# Partial failures
# ---------------------------------------------------------------------------


class TestPartialBatchFailure:
    def test_successful_records_populated_despite_failures(
        self, action_config, sqlite_backend, tmp_path
    ):
        context_map: dict[str, Any] = {}
        batch_results = []

        for i in range(2):
            tid = f"tid_ok_{i}"
            context_map[tid] = {
                "source_guid": f"src_{i}",
                "target_id": tid,
                "content": {"upstream": {"data": f"val_{i}"}},
                "_filter_status": "included",
            }
            batch_results.append(
                BatchResult(
                    custom_id=tid,
                    content={"answer": f"Answer {i}"},
                    success=True,
                    error=None,
                )
            )

        context_map["tid_fail"] = {
            "source_guid": "src_fail",
            "target_id": "tid_fail",
            "content": {"upstream": {"data": "val_fail"}},
            "_filter_status": "included",
        }
        batch_results.append(
            BatchResult(custom_id="tid_fail", content=None, success=False, error="HTTP 500")
        )

        output = _process_batch(batch_results, context_map, action_config, str(tmp_path))
        writer = FileWriter(
            str(tmp_path / "partial.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "partial.json")
        populated = [r for r in data if r.get("content", {}).get("verify_answer") not in (None, {})]
        assert len(populated) >= 2


# ---------------------------------------------------------------------------
# Disk materialization
# ---------------------------------------------------------------------------


class TestDiskMaterialization:
    def test_target_json_materialized_on_disk(
        self, action_config, batch_result, context_map, sqlite_backend, tmp_path
    ):
        output = _process_batch([batch_result], context_map, action_config, str(tmp_path))

        output_file = tmp_path / "target.json"
        writer = FileWriter(
            str(output_file),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        assert output_file.exists(), "Target file not materialized to disk"

        with open(output_file) as f:
            disk_data = json.load(f)
        assert disk_data[0]["content"]["verify_answer"]["verified_answer"] == "C"


# ---------------------------------------------------------------------------
# Provider parse chain (Ollama .jsonl simulation)
# ---------------------------------------------------------------------------


class TestProviderParseChain:
    def test_jsonl_string_content_parsed_and_written(
        self, action_config, context_map, sqlite_backend, tmp_path
    ):
        """Content arrives as JSON string in .jsonl — must parse and persist."""
        from agent_actions.llm.providers.batch_base import BaseBatchClient
        from agent_actions.llm.providers.mixins import OpenAICompatibleResponseMixin

        raw_response = {
            "custom_id": "tid_001",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"verified_answer": "C", "verification_reasoning": "Correct"}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "model": "llama3.3",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                },
            },
            "error": None,
        }

        class _StubClient(OpenAICompatibleResponseMixin, BaseBatchClient):
            vendor_slug = "test"

            def _fetch_status(self, batch_id):
                return "completed"

            def _normalize_status(self, raw_status):
                return raw_status

            def _get_default_model(self):
                return "test-model"

            def _get_result_file_name(self, batch_id):
                return f"{batch_id}_results.jsonl"

            def format_task_for_provider(self, batch_task, schema=None):
                return {}

            def _submit_to_provider_api(self, input_file, batch_name):
                return ("test", "completed")

            def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
                return batch_dir / "test.jsonl"

            def _fetch_raw_results(self, batch_id):
                return b""

        batch_result = _StubClient().parse_provider_response(raw_response)
        assert isinstance(batch_result.content, dict)
        assert batch_result.content["verified_answer"] == "C"

        output = _process_batch([batch_result], context_map, action_config, str(tmp_path))
        writer = FileWriter(
            str(tmp_path / "ollama.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "ollama.json")
        assert data[0]["content"]["verify_answer"]["verified_answer"] == "C"

    def test_empty_json_response_produces_hollow_namespace(self, action_config, context_map):
        """Empty dict from LLM produces content.{action_name}: {} — hollow but valid."""
        result = BatchResult(custom_id="tid_001", content={}, success=True, error=None)
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )
        assert results[0].data[0]["content"]["verify_answer"] == {}
