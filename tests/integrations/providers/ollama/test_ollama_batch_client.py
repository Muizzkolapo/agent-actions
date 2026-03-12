"""
Tests for OllamaBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds Ollama-specific edge cases.

Total tests for Ollama:
- 11 inherited contract tests
- 2 Ollama-specific tests
= 13 total tests
"""

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
