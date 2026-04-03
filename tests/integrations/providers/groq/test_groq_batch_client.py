"""
Tests for GroqBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds Groq-specific edge cases, including the json_object regression test
for issue #96.

Total tests for Groq:
- 11 inherited contract tests
- Additional Groq-specific tests
"""

from unittest.mock import Mock

import pytest

from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestGroqBatchClient(BaseBatchClientTests):
    """
    Tests for GroqBatchClient.

    Inherits 11 contract tests from BaseBatchClientTests.
    Only implements required fixtures and Groq-specific tests.
    """

    @pytest.fixture
    def provider(self):
        """Provide GroqBatchClient instance with mocked client."""
        provider = GroqBatchClient(api_key="test-groq-key-12345")
        mock_client = Mock()
        provider.client = mock_client
        mock_created_batch = Mock()
        mock_created_batch.id = "batch-groq-12345"
        mock_created_batch.status = "validating"
        mock_client.batches.create.return_value = mock_created_batch
        mock_batch = Mock()
        mock_batch.status = "completed"
        mock_batch.output_file_id = "file-output-groq-123"
        mock_client.batches.retrieve.return_value = mock_batch
        mock_file = Mock()
        mock_file.id = "file-input-groq-456"
        mock_client.files.create.return_value = mock_file
        mock_file_content = Mock()
        mock_file_content.content = (
            b'{"custom_id": "1", "response": {"status_code": 200, '
            b'"body": {"choices": [{"message": {"content": "test"}}]}}}\n'
        )
        mock_client.files.content.return_value = mock_file_content
        return provider

    @pytest.fixture
    def provider_success_response_json(self):
        """Mock Groq success response with JSON content (OpenAI-compatible format)."""
        return {
            "custom_id": "test-123",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "chatcmpl-groq-abc123",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "llama-3.3-70b-versatile",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"answer": "4"}'},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                    "system_fingerprint": "fp_groq_test123",
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_success_response_string(self):
        """Mock Groq success response with plain text."""
        return {
            "custom_id": "test-456",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "chatcmpl-groq-def456",
                    "object": "chat.completion",
                    "created": 1234567891,
                    "model": "llama-3.3-70b-versatile",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello world"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                    "system_fingerprint": "fp_groq_test456",
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_error_response(self):
        """Mock Groq error response."""
        return {
            "custom_id": "test-789",
            "response": {"status_code": 404, "body": None},
            "error": {
                "message": "The model 'nonexistent-model' does not exist",
                "type": "invalid_request_error",
                "param": "model",
                "code": "model_not_found",
            },
        }

    # -- Base class overrides --------------------------------------------------

    def test_retrieve_invalid_batch_id_raises_error(self, tmp_path):
        """Override: configure mock to raise for invalid batch ID."""
        from agent_actions.errors import VendorAPIError

        provider = GroqBatchClient(api_key="test-key")
        mock_client = Mock()
        provider.client = mock_client
        mock_client.batches.retrieve.side_effect = VendorAPIError(
            vendor="groq",
            endpoint="batches.retrieve",
            context={"message": "Batch not found", "batch_id": "nonexistent"},
        )
        with pytest.raises(VendorAPIError):
            provider.retrieve_results("nonexistent-batch-id-12345", str(tmp_path))

    # -- Groq-specific tests --------------------------------------------------

    def test_groq_format_task_includes_method_and_url(self, provider, sample_batch_task):
        """Groq uses OpenAI-compatible format with method and url fields."""
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert result["method"] == "POST"
        assert result["url"] == "/v1/chat/completions"
        assert "body" in result
        assert "messages" in result["body"]

    def test_groq_format_task_with_schema_uses_json_object(self, provider, sample_batch_task):
        """Regression test for #96: Groq must use json_object, not json_schema.

        Groq's API supports json_object mode (like the online GroqClient),
        not OpenAI's json_schema mode. Using json_schema causes batch
        submission to fail at runtime.
        """
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert "response_format" in result["body"]
        assert result["body"]["response_format"] == {"type": "json_object"}, (
            "Groq batch must use json_object, not json_schema (issue #96)"
        )

    def test_groq_format_task_without_schema_omits_response_format(
        self, provider, sample_batch_task
    ):
        """Without a schema, response_format should not be set."""
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "response_format" not in result["body"]

    def test_groq_metadata_extraction(self, provider, provider_success_response_json):
        """Groq extracts created and system_fingerprint from response."""
        result = provider.parse_provider_response(provider_success_response_json)
        assert result.metadata is not None
        assert result.metadata["created"] == 1234567890
        assert result.metadata["system_fingerprint"] == "fp_groq_test123"

    def test_groq_default_model(self, provider):
        """Groq default model is llama-3.3-70b-versatile."""
        assert provider._get_default_model() == "llama-3.3-70b-versatile"
