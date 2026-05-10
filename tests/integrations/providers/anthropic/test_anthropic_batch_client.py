"""
Tests for AnthropicBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds Anthropic-specific edge cases.

Total tests for Anthropic:
- 11 inherited contract tests
- Additional Anthropic-specific tests
"""

from unittest.mock import Mock, patch

import pytest

from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestAnthropicBatchClient(BaseBatchClientTests):
    """
    Tests for AnthropicBatchClient.

    Inherits 11 contract tests from BaseBatchClientTests.
    Only implements required fixtures and Anthropic-specific tests.
    """

    @pytest.fixture
    def provider(self):
        """
        Provide AnthropicBatchClient instance with mocked client.

        Mock the Anthropic client to avoid requiring actual API key and HTTP calls.
        """
        mock_anthropic_module = Mock()
        mock_client = Mock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_anthropic_module.APIError = Exception
        with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
            provider = AnthropicBatchClient(api_key="test-anthropic-key")
            provider.client = mock_client
            mock_batch = Mock()
            mock_batch.id = "msgbatch_test123"
            mock_batch.processing_status = "ended"
            mock_batch.results_url = "https://test.com/results"
            mock_client.messages.batches.create.return_value = mock_batch
            mock_client.messages.batches.retrieve.return_value = mock_batch
            mock_results_response = Mock()
            mock_results_response.text = '{"custom_id": "test-1", "result": {"type": "succeeded", "message": {"content": [{"type": "text", "text": "Hello"}]}}}'
            mock_client.messages.batches.results.return_value = mock_results_response
            yield provider

    @pytest.fixture
    def provider_success_response_json(self):
        """
        Mock Anthropic success response with JSON content (tool use).

        Anthropic uses tool_use for structured output, not JSON mode.
        """
        return {
            "custom_id": "test-123",
            "result": {
                "type": "succeeded",
                "message": {
                    "id": "msg_01abc123",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01xyz",
                            "name": "json_tool",
                            "input": {"answer": "4"},
                        }
                    ],
                    "model": "claude-3-5-sonnet-20241022",
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            },
        }

    @pytest.fixture
    def provider_success_response_string(self):
        """Mock Anthropic success response with plain text."""
        return {
            "custom_id": "test-456",
            "result": {
                "type": "succeeded",
                "message": {
                    "id": "msg_02def456",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello world"}],
                    "model": "claude-3-5-sonnet-20241022",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 80, "output_tokens": 20},
                },
            },
        }

    @pytest.fixture
    def provider_error_response(self):
        """Mock Anthropic error response."""
        return {
            "custom_id": "test-789",
            "result": {
                "type": "errored",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Model 'invalid-model' does not exist",
                },
            },
        }

    def test_anthropic_format_task_uses_params_not_body(self, provider, sample_batch_task):
        """
        Anthropic-specific: Verify task format uses 'params' not 'body'.

        Anthropic Message Batches API uses different structure than OpenAI.
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "params" in result, "Anthropic requires 'params' field"
        assert "body" not in result, "Anthropic doesn't use 'body' field"
        assert "messages" in result["params"], "Anthropic requires messages in params"
        assert "model" in result["params"], "Anthropic requires model in params"

    def test_anthropic_format_task_system_as_top_level(self, provider, sample_batch_task):
        """
        Anthropic-specific: Verify system message is top-level param.

        Anthropic puts system message at top level, not in messages array.
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "system" in result["params"], "Anthropic requires system at top level"
        assert result["params"]["system"] == "You are a helpful assistant"
        messages = result["params"]["messages"]
        assert len(messages) == 1, "Only user message should be in messages array"
        assert messages[0]["role"] == "user"

    def test_anthropic_format_task_with_schema_uses_tools(self, provider, sample_batch_task):
        """
        Anthropic-specific: Verify schema is converted to tools.

        Anthropic uses tool calling for structured output, not response_format.
        """
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert "tools" in result["params"], "Anthropic should use tools for structured output"
        assert "tool_choice" in result["params"], "Anthropic should specify tool_choice"
        assert isinstance(result["params"]["tools"], list), "Tools should be a list"
        assert len(result["params"]["tools"]) > 0, "Should have at least one tool"

    def test_submit_and_retrieve_workflow(
        self, provider, tmp_path, sample_data, sample_agent_config_no_json_mode
    ):
        """Test submit and retrieve workflow with Anthropic provider."""
        # Prepare tasks
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)
        assert len(tasks) == 3

        # Submit batch - returns (batch_id, status) tuple
        result = provider.submit_batch(tasks, str(tmp_path))
        batch_id = result[0] if isinstance(result, tuple) else result
        assert batch_id is not None
        assert "msgbatch" in batch_id

    # -----------------------------------------------------------------
    # Error extraction tests
    # -----------------------------------------------------------------

    def test_errored_result_extracts_error_info(self, provider, provider_error_response):
        """Errored results return the actual error message, not 'Unknown result type'."""
        error = provider._extract_error_from_response(provider_error_response)
        assert error is not None
        assert "invalid_request_error" in error
        assert "Unknown result type" not in error

    def test_succeeded_result_returns_none(self, provider, provider_success_response_json):
        """Succeeded results return None (no error)."""
        error = provider._extract_error_from_response(provider_success_response_json)
        assert error is None

    def test_expired_result_returns_clear_error(self, provider):
        """Expired results produce a clear error, not 'Unknown result type'."""
        response = {"custom_id": "test", "result": {"type": "expired"}}
        error = provider._extract_error_from_response(response)
        assert error is not None
        assert "expired" in error.lower()
        assert "Unknown result type" not in error

    def test_canceled_result_returns_clear_error(self, provider):
        """Canceled results produce a clear error."""
        response = {"custom_id": "test", "result": {"type": "canceled"}}
        error = provider._extract_error_from_response(response)
        assert error is not None
        assert "canceled" in error.lower()
        assert "Unknown result type" not in error

    def test_missing_result_returns_format_error(self, provider):
        """Missing result field returns format error."""
        error = provider._extract_error_from_response({"custom_id": "test"})
        assert error is not None
        assert "Invalid response format" in error

    def test_unknown_result_type_includes_type_name(self, provider):
        """Unknown result types include the type in the error message."""
        response = {"custom_id": "test", "result": {"type": "new_type"}}
        error = provider._extract_error_from_response(response)
        assert error is not None
        assert "new_type" in error

    def test_errored_result_without_error_info_returns_fallback(self, provider):
        """Errored result with no error details returns fallback message."""
        response = {"custom_id": "test", "result": {"type": "errored"}}
        error = provider._extract_error_from_response(response)
        assert error is not None
        assert "errored" in error.lower()

    def test_retrieve_invalid_batch_id_raises_error(self, tmp_path):
        """Override to test error handling with proper mock."""
        from agent_actions.errors import VendorAPIError

        mock_anthropic_module = Mock()
        mock_client = Mock()
        mock_anthropic_module.Anthropic.return_value = mock_client
        mock_anthropic_module.APIError = Exception
        with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
            provider = AnthropicBatchClient(api_key="test-key")
            provider.client = mock_client
            mock_client.messages.batches.retrieve.side_effect = VendorAPIError(
                vendor="anthropic",
                endpoint="messages.batches.retrieve",
                context={"message": "Batch not found"},
            )
            with pytest.raises(VendorAPIError):
                provider.retrieve_results("nonexistent-batch-id", str(tmp_path))
