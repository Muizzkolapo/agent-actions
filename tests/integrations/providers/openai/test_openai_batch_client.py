"""
Tests for OpenAIBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds OpenAI-specific edge cases.

Total tests for OpenAI:
- 11 inherited contract tests
- Additional OpenAI-specific tests (as needed)
"""

from unittest.mock import Mock

import pytest

from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestOpenAIBatchClient(BaseBatchClientTests):
    """
    Tests for OpenAIBatchClient.

    Inherits 11 contract tests from BaseBatchClientTests.
    Only implements required fixtures and OpenAI-specific tests.
    """

    @pytest.fixture
    def provider(self):
        """Provide OpenAIBatchClient instance with mocked client."""
        provider = OpenAIBatchClient(api_key="test-api-key-12345")
        mock_client = Mock()
        provider.client = mock_client
        mock_created_batch = Mock()
        mock_created_batch.id = "batch-test-12345"
        mock_created_batch.status = "validating"
        mock_client.batches.create.return_value = mock_created_batch
        mock_batch = Mock()
        mock_batch.status = "completed"
        mock_batch.output_file_id = "file-output-123"
        mock_client.batches.retrieve.return_value = mock_batch
        mock_file = Mock()
        mock_file.id = "file-input-456"
        mock_client.files.create.return_value = mock_file
        mock_file_content = Mock()
        mock_file_content.content = b'{"custom_id": "1", "response": {"status_code": 200, "body": {"choices": [{"message": {"content": "test"}}]}}}\n'
        mock_client.files.content.return_value = mock_file_content
        return provider

    @pytest.fixture
    def provider_success_response_json(self):
        """
        Mock OpenAI success response with JSON content.

        OpenAI Batch API format with structured JSON output.
        """
        return {
            "custom_id": "test-123",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "chatcmpl-abc123",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"answer": "4"}'},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                    "system_fingerprint": "fp_test123",
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_success_response_string(self):
        """Mock OpenAI success response with plain text."""
        return {
            "custom_id": "test-456",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "chatcmpl-def456",
                    "object": "chat.completion",
                    "created": 1234567891,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello world"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                    "system_fingerprint": "fp_test456",
                },
            },
            "error": None,
        }

    @pytest.fixture
    def provider_error_response(self):
        """Mock OpenAI error response."""
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

    def test_openai_format_task_includes_method_and_url(self, provider, sample_batch_task):
        """
        OpenAI-specific: Verify task format includes method and url fields.

        OpenAI Batch API requires specific format with method and url.
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert result["method"] == "POST", "OpenAI requires method=POST"
        assert result["url"] == "/v1/chat/completions", "OpenAI requires chat completions URL"
        assert "body" in result, "OpenAI requires body field"
        assert "messages" in result["body"], "OpenAI requires messages in body"

    def test_openai_format_task_with_schema_includes_response_format(
        self, provider, sample_batch_task
    ):
        """
        OpenAI-specific: Verify schema is added as response_format.

        OpenAI uses response_format with json_schema type.
        """
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert "response_format" in result["body"], "OpenAI requires response_format for schema"
        assert result["body"]["response_format"]["type"] == "json_schema"
        assert "json_schema" in result["body"]["response_format"]

    def test_openai_parse_response_extracts_usage_metadata(
        self, provider, provider_success_response_json
    ):
        """
        OpenAI-specific: Verify usage metadata is correctly extracted.

        OpenAI provides detailed token usage information.
        """
        result = provider.parse_provider_response(provider_success_response_json)
        assert result.usage is not None, "OpenAI responses should include usage"
        assert result.usage["prompt_tokens"] == 12
        assert result.usage["completion_tokens"] == 8
        assert result.usage["total_tokens"] == 20
        assert result.metadata is not None
        assert result.metadata["model"] == "gpt-4o-mini"
        assert result.metadata["finish_reason"] == "stop"
        assert result.metadata["system_fingerprint"] == "fp_test123"

    def test_retrieve_invalid_batch_id_raises_error(self, tmp_path):
        """
        Test error handling for invalid batch ID (OpenAI-specific override).

        Since we mock the client, we need to configure it to raise an error
        for this specific test.
        """
        from agent_actions.errors import VendorAPIError

        provider = OpenAIBatchClient(api_key="test-key")
        mock_client = Mock()
        provider.client = mock_client
        mock_client.batches.retrieve.side_effect = VendorAPIError(
            vendor="openai",
            endpoint="batches.retrieve",
            context={"message": "Batch not found", "batch_id": "nonexistent"},
        )
        with pytest.raises(VendorAPIError):
            provider.retrieve_results("nonexistent-batch-id-12345", str(tmp_path))
