"""
Tests for GroqBatchClient.

Inherits 11 contract tests from BaseBatchClientTests.
Adds Groq-specific tests including the json_object regression test for #96.
"""

from unittest.mock import Mock

import pytest

from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestGroqBatchClient(BaseBatchClientTests):
    """Tests for GroqBatchClient — contract tests + Groq-specific behavior."""

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

    def test_format_task_with_schema_passes_json_schema(self, provider, sample_batch_task):
        """Groq now supports json_schema structured output — schema must reach the API."""
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)

        assert result["body"]["response_format"] == {
            "type": "json_schema",
            "json_schema": schema,
        }

    def test_format_task_without_schema_omits_response_format(self, provider, sample_batch_task):
        """No schema means no response_format — Groq returns free-form text."""
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "response_format" not in result["body"]

    def test_format_task_envelope_is_openai_compatible(self, provider, sample_batch_task):
        """Groq batch API uses the OpenAI-compatible JSONL envelope format."""
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert result["method"] == "POST"
        assert result["url"] == "/v1/chat/completions"
        assert "messages" in result["body"]

    def test_metadata_includes_groq_specific_fields(self, provider, provider_success_response_json):
        """Groq responses include created timestamp and system_fingerprint."""
        result = provider.parse_provider_response(provider_success_response_json)
        assert result.metadata["created"] == 1234567890
        assert result.metadata["system_fingerprint"] == "fp_groq_test123"
