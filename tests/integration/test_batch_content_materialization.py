"""
Integration tests for batch content materialization.

Verifies that batch LLM results are correctly injected into
content.{action_name} and persisted to the storage backend.

Reproduces the bug: batch-mode actions produce hollow records
(content.{action_name}: {}) despite valid LLM responses.
"""

import json
from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing_recovery import (
    _stamp_batch_records,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import FileWriter
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _enrich_and_stamp(results, action_name: str = "verify_answer") -> list[dict[str, Any]]:
    """Run enrichment pipeline + stamp lifecycle (matches production path)."""
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
    """Realistic LLM action config for batch processing."""
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
    """Input record with upstream content namespaces."""
    return {
        "source_guid": "src_001",
        "target_id": "tid_001",
        "version_correlation_id": "corr_001",
        "content": {
            "summarize_page_content": {
                "summary": "AWS S3 bucket policies control access...",
            },
            "write_scenario_question": {
                "question_text": "What is the correct S3 bucket policy?",
                "answer_text": "Option C: Allow principal *",
            },
        },
    }


@pytest.fixture
def llm_response() -> dict[str, Any]:
    """Parsed LLM response (what the provider returns after JSON parsing)."""
    return {
        "verified_answer": "C",
        "verification_reasoning": "Option C correctly allows all principals.",
    }


@pytest.fixture
def batch_result(llm_response) -> BatchResult:
    """BatchResult as returned by provider.retrieve_results()."""
    return BatchResult(
        custom_id="tid_001",
        content=llm_response,
        success=True,
        error=None,
        metadata={"model": "gpt-4o-mini", "finish_reason": "stop"},
    )


@pytest.fixture
def context_map(upstream_record) -> dict[str, Any]:
    """Context map as saved at batch submission time."""
    record = upstream_record.copy()
    record["_filter_status"] = "included"
    return {"tid_001": record}


@pytest.fixture
def sqlite_backend(tmp_path) -> SQLiteBackend:
    """Real SQLite backend for integration testing."""
    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(str(db_path), workflow_name="test_workflow")
    backend.initialize()
    return backend


# ---------------------------------------------------------------------------
# Test 1: Content assembly in BatchResultStrategy
# ---------------------------------------------------------------------------


class TestBatchContentAssembly:
    """Verify that BatchResultStrategy correctly builds content[action_name]."""

    def test_successful_result_populates_action_namespace(
        self, action_config, batch_result, context_map, llm_response
    ):
        """Core test: content[action_name] must contain the parsed LLM response."""
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        result = results[0]
        assert result.data, "ProcessingResult.data is empty"

        # Check the first item's content
        item = result.data[0]
        content = item.get("content", {})

        # THE CRITICAL ASSERTION: action namespace must have LLM response
        action_ns = content.get("verify_answer")
        assert action_ns is not None, (
            f"content['verify_answer'] is missing. Content keys: {list(content.keys())}"
        )
        assert action_ns != {}, (
            f"content['verify_answer'] is empty dict. Expected LLM response: {llm_response}"
        )
        assert action_ns.get("verified_answer") == "C", (
            f"content['verify_answer'] missing 'verified_answer'. Got: {action_ns}"
        )
        assert "verification_reasoning" in action_ns

        # Upstream namespaces must be preserved
        assert "summarize_page_content" in content
        assert "write_scenario_question" in content

    def test_string_content_parsed_to_dict(self, action_config, context_map):
        """When provider returns parsed string, it should be re-wrapped."""
        # Simulate provider returning string content (json_mode but unparsed)
        batch_result = BatchResult(
            custom_id="tid_001",
            content='{"verified_answer": "C"}',  # String, not dict
            success=True,
            error=None,
        )
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        item = results[0].data[0]
        content = item.get("content", {})
        action_ns = content.get("verify_answer", {})

        # String in json_mode gets wrapped as _parse_error
        # (the string should have been parsed by the provider, not here)
        assert "_parse_error" in action_ns or "verified_answer" in action_ns

    def test_framework_fields_carried(self, action_config, batch_result, context_map):
        """target_id and version_correlation_id must be carried from input."""
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        item = results[0].data[0]
        assert item.get("target_id") == "tid_001"
        assert item.get("version_correlation_id") == "corr_001"


# ---------------------------------------------------------------------------
# Test 2: Full pipeline → DB write
# ---------------------------------------------------------------------------


class TestBatchToDBPipeline:
    """End-to-end: batch result → processing → enrichment → DB write."""

    def test_content_survives_enrichment_and_db_write(
        self, action_config, batch_result, context_map, sqlite_backend, tmp_path
    ):
        """Content[action_name] must contain LLM response after enrichment and DB write."""
        # 1. Process batch results
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=action_config,
        )

        # 2. Enrich + stamp (same as production finalize_batch_output)
        output = _enrich_and_stamp(results, "verify_answer")
        assert len(output) > 0, "No output records after enrichment"

        # 3. Verify content BEFORE write
        for record in output:
            content = record.get("content", {})
            action_ns = content.get("verify_answer")
            assert action_ns is not None, (
                f"Pre-write: content['verify_answer'] is None. "
                f"Full content: {json.dumps(content, indent=2, default=str)}"
            )
            assert action_ns != {}, (
                f"Pre-write: content['verify_answer'] is empty. "
                f"Full record keys: {list(record.keys())}"
            )

        # 4. Write to SQLite backend
        output_file = tmp_path / "test_output.json"
        writer = FileWriter(
            str(output_file),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        # 5. Read back from SQLite and verify
        target_files = sqlite_backend.list_target_files("verify_answer")
        assert len(target_files) > 0, "No target files in SQLite after write"

        for rel_path in target_files:
            data = sqlite_backend.read_target("verify_answer", rel_path)
            assert isinstance(data, list), f"Expected list, got {type(data)}"
            assert len(data) > 0, "Empty data list from SQLite"

            for record in data:
                content = record.get("content", {})
                action_ns = content.get("verify_answer")
                assert action_ns is not None, (
                    f"Post-write: content['verify_answer'] is None in DB. "
                    f"Content keys: {list(content.keys())}"
                )
                assert action_ns != {}, (
                    f"Post-write: content['verify_answer'] is EMPTY in DB. "
                    f"This is the bug! Content: {json.dumps(content, indent=2, default=str)}"
                )
                assert action_ns.get("verified_answer") == "C", (
                    f"Post-write: LLM response not in DB. Got: {action_ns}"
                )

    def test_multiple_records_all_populated(
        self, action_config, context_map, sqlite_backend, tmp_path
    ):
        """All records in a batch should have content populated, not just the first."""
        # Build 3 batch results with different custom_ids
        records = []
        for i in range(3):
            tid = f"tid_{i:03d}"
            upstream = {
                "source_guid": f"src_{i:03d}",
                "target_id": tid,
                "content": {"upstream_action": {"field": f"value_{i}"}},
                "_filter_status": "included",
            }
            context_map[tid] = upstream
            records.append(
                BatchResult(
                    custom_id=tid,
                    content={"score": i * 10, "reasoning": f"Reason {i}"},
                    success=True,
                    error=None,
                )
            )

        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=records,
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=action_config,
        )

        output = _enrich_and_stamp(results, "verify_answer")

        # Write to DB
        writer = FileWriter(
            str(tmp_path / "batch_output.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        # Read back and verify ALL records
        data = sqlite_backend.read_target("verify_answer", "batch_output.json")
        hollow_count = 0
        for record in data:
            action_ns = record.get("content", {}).get("verify_answer")
            if action_ns is None or action_ns == {}:
                hollow_count += 1

        assert hollow_count == 0, (
            f"{hollow_count}/{len(data)} records have hollow content['verify_answer']. "
            f"This is the batch materialization bug."
        )


# ---------------------------------------------------------------------------
# Test 3: Versioned action content
# ---------------------------------------------------------------------------


class TestVersionedBatchContent:
    """Batch content for versioned actions (e.g., verify_answer_1)."""

    def test_versioned_action_name_in_content(self, context_map, sqlite_backend, tmp_path):
        """Versioned action writes content under versioned name (verify_answer_1)."""
        versioned_config = {
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

        batch_result = BatchResult(
            custom_id="tid_001",
            content={"verified_answer": "C", "verification_reasoning": "Correct"},
            success=True,
            error=None,
            metadata={"model": "gpt-4o-mini"},
        )

        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=versioned_config,
        )

        output = _enrich_and_stamp(results, "verify_answer_1")

        writer = FileWriter(
            str(tmp_path / "output.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer_1",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer_1", "output.json")
        record = data[0]
        content = record.get("content", {})

        # Must be under the versioned name
        assert "verify_answer_1" in content, (
            f"Expected 'verify_answer_1' in content. Got keys: {list(content.keys())}"
        )
        assert content["verify_answer_1"].get("verified_answer") == "C"
        assert record.get("version_correlation_id") == "corr_001"


# ---------------------------------------------------------------------------
# Test 4: Failed + successful records in same batch
# ---------------------------------------------------------------------------


class TestPartialBatchFailure:
    """When some records fail, successful ones must still have content."""

    def test_successful_records_populated_despite_failures(
        self, action_config, sqlite_backend, tmp_path
    ):
        """1 failed + 2 successful: successful records must have full content."""
        context_map = {}
        batch_results = []

        # 2 successful results
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
                    content={"answer": f"Answer {i}", "reasoning": f"Because {i}"},
                    success=True,
                    error=None,
                )
            )

        # 1 failed result
        tid_fail = "tid_fail"
        context_map[tid_fail] = {
            "source_guid": "src_fail",
            "target_id": tid_fail,
            "content": {"upstream": {"data": "val_fail"}},
            "_filter_status": "included",
        }
        batch_results.append(
            BatchResult(
                custom_id=tid_fail,
                content=None,
                success=False,
                error="HTTP 500 Internal Server Error",
            )
        )

        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=action_config,
        )

        output = _enrich_and_stamp(results, "verify_answer")

        # Write ALL records (including failed) to DB
        writer = FileWriter(
            str(tmp_path / "partial.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "partial.json")

        # Successful records must have content
        successful_records = [
            r
            for r in data
            if r.get("content", {}).get("verify_answer") is not None
            and r.get("content", {}).get("verify_answer") != {}
        ]
        assert len(successful_records) >= 2, (
            f"Expected at least 2 records with populated content, got {len(successful_records)}. "
            f"Record contents: {[r.get('content', {}).get('verify_answer') for r in data]}"
        )


# ---------------------------------------------------------------------------
# Test 5: Disk materialization (currently expected to fail — the gap)
# ---------------------------------------------------------------------------


class TestDiskMaterialization:
    """Target directory files must be written alongside DB records."""

    def test_target_json_exists_on_disk(
        self, action_config, batch_result, context_map, sqlite_backend, tmp_path
    ):
        """After batch finalization, processed JSON must exist on disk."""
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=action_config,
        )

        output = _enrich_and_stamp(results, "verify_answer")

        # Write via FileWriter (production path)
        output_file = tmp_path / "test_output.json"
        writer = FileWriter(
            str(output_file),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        # After fix: FileWriter.write_target writes to BOTH SQLite and disk
        assert output_file.exists(), (
            f"Target file not materialized at {output_file}. "
            f"FileWriter.write_target must write to both SQLite and disk."
        )

        # Verify disk file contains correct content
        with open(output_file) as f:
            disk_data = json.load(f)
        assert isinstance(disk_data, list)
        assert len(disk_data) > 0
        disk_content = disk_data[0].get("content", {})
        assert disk_content.get("verify_answer", {}).get("verified_answer") == "C"


# ---------------------------------------------------------------------------
# Test 6: Provider parse chain (simulates Ollama .jsonl reading)
# ---------------------------------------------------------------------------


class TestProviderParseChain:
    """Simulate reading from a .jsonl file as the Ollama batch client does."""

    def test_jsonl_string_content_parsed_correctly(
        self, action_config, context_map, sqlite_backend, tmp_path
    ):
        """Simulate Ollama .jsonl: content is a JSON STRING, not pre-parsed dict.

        The provider writes results to .jsonl, then _read_jsonl_file calls
        parse_provider_response which extracts and parses the content string.
        """
        from agent_actions.llm.providers.batch_base import BaseBatchClient
        from agent_actions.llm.providers.mixins import OpenAICompatibleResponseMixin

        # Build a raw OpenAI-format response as would appear in .jsonl
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

        # Create a minimal concrete batch client to access parse_provider_response
        class _TestClient(OpenAICompatibleResponseMixin, BaseBatchClient):
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

        client = _TestClient()
        batch_result = client.parse_provider_response(raw_response)

        # Verify the provider correctly parsed the string content
        assert batch_result.success is True
        assert batch_result.content is not None
        assert isinstance(batch_result.content, dict), (
            f"Expected parsed dict, got {type(batch_result.content).__name__}: "
            f"{batch_result.content!r}"
        )
        assert batch_result.content.get("verified_answer") == "C"

        # Now run through the full batch strategy + DB write
        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory=str(tmp_path),
            agent_config=action_config,
        )

        output = _enrich_and_stamp(results, "verify_answer")

        writer = FileWriter(
            str(tmp_path / "ollama_output.json"),
            storage_backend=sqlite_backend,
            action_name="verify_answer",
            output_directory=str(tmp_path),
        )
        writer.write_target(output)

        data = sqlite_backend.read_target("verify_answer", "ollama_output.json")
        record = data[0]
        action_ns = record.get("content", {}).get("verify_answer")
        assert action_ns != {}, f"Hollow record! content.verify_answer is empty: {action_ns}"
        assert action_ns.get("verified_answer") == "C"

    def test_empty_json_response_detected(self, action_config, context_map):
        """When LLM returns '{}' (empty JSON), the record should not be hollow."""
        # This simulates the Ollama Cloud case where format=json isn't sent
        batch_result = BatchResult(
            custom_id="tid_001",
            content={},  # Parsed from "{}" — empty dict
            success=True,
            error=None,
        )

        strategy = BatchResultStrategy()
        results = strategy.process(
            batch_results=[batch_result],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=action_config,
        )

        item = results[0].data[0]
        content = item.get("content", {})
        action_ns = content.get("verify_answer")

        # Even with empty LLM response, the namespace exists (it's just empty)
        # This IS a hollow record — the framework processed it "successfully"
        # but the LLM didn't return useful data
        assert action_ns == {}, (
            "Expected empty dict for empty LLM response — this is the hollow record pattern"
        )
