"""
Tests for OllamaBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds Ollama-specific edge cases and concurrency tests.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestOllamaBatchClient(BaseBatchClientTests):
    """
    Tests for OllamaBatchClient.

    Inherits 11 contract tests from BaseBatchClientTests.
    Only implements required fixtures and Ollama-specific tests.
    """

    @pytest.fixture
    def provider(self):
        """Provide OllamaBatchClient instance."""
        return OllamaBatchClient(base_url="http://localhost:11434")

    @pytest.fixture
    def provider_success_response_json(self):
        """
        Mock Ollama success response with JSON content (OpenAI format).

        Ollama uses OpenAI-compatible format for consistency.
        """
        return {
            "custom_id": "test-123",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": '{"answer": "4"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_success_response_string(self):
        """Mock Ollama success response with plain text."""
        return {
            "custom_id": "test-456",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": "Hello world"}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_error_response(self):
        """Mock Ollama error response."""
        return {
            "custom_id": "test-789",
            "response": None,
            "error": {
                "message": "Model not found",
                "type": "ollama_error",
                "code": "model_not_found",
            },
        }

    def test_ollama_transform_response(self, provider):
        """
        Test Ollama-specific response transformation.

        Validates that Ollama's native format is correctly transformed
        to OpenAI-compatible format.
        """
        ollama_raw_response = {
            "model": "llama2",
            "message": {"role": "assistant", "content": "Hello from Ollama"},
            "done": True,
            "prompt_eval_count": 15,
            "eval_count": 8,
        }
        result = provider._transform_ollama_response(
            ollama_raw_response, custom_id="test-transform", model="llama2"
        )
        assert result["custom_id"] == "test-transform"
        assert result["response"]["status_code"] == 200
        assert result["response"]["body"]["model"] == "llama2"
        assert result["response"]["body"]["choices"][0]["message"]["content"] == "Hello from Ollama"
        assert result["response"]["body"]["usage"]["prompt_tokens"] == 15
        assert result["response"]["body"]["usage"]["completion_tokens"] == 8
        assert result["response"]["body"]["usage"]["total_tokens"] == 23
        assert result["error"] is None


# ── Concurrency tests ───────────────────────────────────────────────


def _make_ollama_response(content: str = "ok") -> dict:
    """Build a minimal Ollama chat response dict."""
    return {
        "model": "llama2",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": 5,
        "eval_count": 3,
    }


def _make_task(custom_id: str) -> dict:
    """Build a minimal JSONL task dict."""
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "llama2",
            "messages": [{"role": "user", "content": "hello"}],
        },
    }


class TestOllamaBatchConcurrency:
    """Tests for concurrent batch processing and max_workers config."""

    def test_default_max_workers_is_one(self):
        """No behavior change without opt-in."""
        client = OllamaBatchClient(base_url="http://localhost:11434")
        assert client._get_max_workers() == 1

    def test_max_workers_from_constructor(self):
        """Constructor param is used directly."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=4)
        assert client._get_max_workers() == 4

    def test_max_workers_from_env_var(self, monkeypatch):
        """Env var OLLAMA_BATCH_MAX_WORKERS is respected."""
        monkeypatch.setenv("OLLAMA_BATCH_MAX_WORKERS", "6")
        client = OllamaBatchClient(base_url="http://localhost:11434")
        assert client._get_max_workers() == 6

    def test_max_workers_constructor_overrides_env(self, monkeypatch):
        """Constructor param takes precedence over env var."""
        monkeypatch.setenv("OLLAMA_BATCH_MAX_WORKERS", "8")
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=2)
        assert client._get_max_workers() == 2

    def test_max_workers_env_invalid_uses_default(self, monkeypatch):
        """Non-integer env var falls back to default."""
        monkeypatch.setenv("OLLAMA_BATCH_MAX_WORKERS", "not_a_number")
        client = OllamaBatchClient(base_url="http://localhost:11434")
        assert client._get_max_workers() == 1

    def test_max_workers_env_zero_uses_default(self, monkeypatch):
        """Zero env var falls back to default (must be >= 1)."""
        monkeypatch.setenv("OLLAMA_BATCH_MAX_WORKERS", "0")
        client = OllamaBatchClient(base_url="http://localhost:11434")
        assert client._get_max_workers() == 1

    def test_max_workers_constructor_negative_uses_default(self):
        """Negative constructor value falls back to default."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=-1)
        assert client._get_max_workers() == 1

    def test_max_workers_constructor_zero_uses_default(self):
        """Zero constructor value falls back to default."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=0)
        assert client._get_max_workers() == 1

    def test_max_workers_clamped_at_limit(self):
        """Values above limit are clamped to 32."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=500)
        assert client._get_max_workers() == 32

    def test_max_workers_at_limit_is_allowed(self):
        """Exactly at the limit is fine."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=32)
        assert client._get_max_workers() == 32

    def test_cloud_default_max_workers(self):
        """Cloud client also defaults to 1."""
        client = OllamaBatchClient(
            base_url="https://ollama.com",
            api_key="test-key-1234567890",
            cloud=True,
            vendor_slug="ollama_cloud",
        )
        assert client._get_max_workers() == 1

    def test_concurrent_processes_all_records(self, tmp_path):
        """All custom_ids present in results with max_workers=4."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=4)
        client.client = MagicMock()
        client.client.chat = MagicMock(return_value=_make_ollama_response())

        tasks = [_make_task(f"rec-{i}") for i in range(10)]
        input_file = tmp_path / "batch" / "input.jsonl"
        input_file.parent.mkdir(parents=True)
        with open(input_file, "w") as f:
            for task in tasks:
                f.write(json.dumps(task) + "\n")

        batch_id, status = client._submit_to_provider_api(input_file, "test_batch")

        assert status == "submitted"
        output_file = input_file.parent / f"{batch_id}_results.jsonl"
        assert output_file.exists()

        results = []
        with open(output_file) as f:
            for line in f:
                results.append(json.loads(line))

        result_ids = {r["custom_id"] for r in results}
        expected_ids = {f"rec-{i}" for i in range(10)}
        assert result_ids == expected_ids

    def test_concurrent_error_isolation(self, tmp_path):
        """One task error doesn't kill others."""
        client = OllamaBatchClient(base_url="http://localhost:11434", max_workers=3)
        client.client = MagicMock()

        def side_effect(model, messages, options, format):
            # Fail for rec-2 only
            if messages == [{"role": "user", "content": "fail"}]:
                raise RuntimeError("simulated error")
            return _make_ollama_response()

        client.client.chat = MagicMock(side_effect=side_effect)

        tasks = [_make_task(f"rec-{i}") for i in range(5)]
        # Make rec-2 trigger the error
        tasks[2]["body"]["messages"] = [{"role": "user", "content": "fail"}]

        input_file = tmp_path / "batch" / "input.jsonl"
        input_file.parent.mkdir(parents=True)
        with open(input_file, "w") as f:
            for task in tasks:
                f.write(json.dumps(task) + "\n")

        batch_id, _ = client._submit_to_provider_api(input_file, "test_batch")
        output_file = input_file.parent / f"{batch_id}_results.jsonl"

        results = []
        with open(output_file) as f:
            for line in f:
                results.append(json.loads(line))

        assert len(results) == 5
        error_results = [r for r in results if r.get("error") is not None]
        success_results = [r for r in results if r.get("error") is None]
        assert len(error_results) == 1
        assert error_results[0]["custom_id"] == "rec-2"
        assert len(success_results) == 4

    def test_sequential_preserved_with_default(self, tmp_path):
        """max_workers=1 (default) produces correct results."""
        client = OllamaBatchClient(base_url="http://localhost:11434")
        client.client = MagicMock()
        client.client.chat = MagicMock(return_value=_make_ollama_response("sequential"))

        tasks = [_make_task(f"seq-{i}") for i in range(3)]
        input_file = tmp_path / "batch" / "input.jsonl"
        input_file.parent.mkdir(parents=True)
        with open(input_file, "w") as f:
            for task in tasks:
                f.write(json.dumps(task) + "\n")

        batch_id, _ = client._submit_to_provider_api(input_file, "test_batch")
        output_file = input_file.parent / f"{batch_id}_results.jsonl"

        results = []
        with open(output_file) as f:
            for line in f:
                results.append(json.loads(line))

        result_ids = {r["custom_id"] for r in results}
        assert result_ids == {"seq-0", "seq-1", "seq-2"}
        for r in results:
            assert r["error"] is None
            assert r["response"]["body"]["choices"][0]["message"]["content"] == "sequential"
