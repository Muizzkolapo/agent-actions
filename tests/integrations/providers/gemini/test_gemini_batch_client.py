"""
Tests for GeminiBatchClient.

This test suite inherits all 11 contract tests from BaseBatchClientTests
and adds Gemini-specific edge cases.

Total tests for Gemini:
- 11 inherited contract tests
- Additional Gemini-specific tests
"""

from unittest.mock import Mock, patch

import pytest

from tests.integrations.providers.base_batch_client_tests import BaseBatchClientTests


class TestGeminiBatchClient(BaseBatchClientTests):
    """
    Tests for GeminiBatchClient.

    Inherits 11 contract tests from BaseBatchClientTests.
    Only implements required fixtures and Gemini-specific tests.
    """

    @pytest.fixture
    def provider(self):
        """
        Provide GeminiBatchClient instance with mocked client.

        Mock the Gemini client to avoid requiring actual API key and HTTP calls.
        """
        mock_genai_module = Mock()
        mock_types_module = Mock()
        mock_client = Mock()
        mock_genai_module.Client.return_value = mock_client
        mock_batch = Mock()
        mock_batch.name = "projects/test/locations/us-central1/batches/batch123"
        mock_state = Mock()
        mock_state.name = "JOB_STATE_SUCCEEDED"
        mock_batch.state = mock_state
        mock_batch.output_uri_prefix = "gs://test-bucket/output"
        mock_client.batches.create.return_value = mock_batch
        mock_client.batches.get.return_value = mock_batch
        mock_file = Mock()
        mock_file.name = "files/test-file-123"
        mock_client.files.upload.return_value = mock_file
        mock_client.files.download.return_value = b'{"key": "test-1", "response": {"candidates": [{"content": {"parts": [{"text": "test"}]}}]}}\n'
        with patch.dict(
            "sys.modules",
            {
                "google": Mock(),
                "google.genai": mock_genai_module,
                "google.genai.types": mock_types_module,
            },
        ):
            with patch("agent_actions.llm.providers.gemini.batch_client.GEMINI_AVAILABLE", True):
                with patch(
                    "agent_actions.llm.providers.gemini.batch_client.genai",
                    mock_genai_module,
                ):
                    with patch(
                        "agent_actions.llm.providers.gemini.batch_client.types",
                        mock_types_module,
                    ):
                        from agent_actions.llm.providers.gemini.batch_client import (
                            GeminiBatchClient,
                        )

                        provider = GeminiBatchClient(api_key="test-gemini-key")
                        provider.client = mock_client
                        yield provider

    @pytest.fixture
    def provider_success_response_json(self):
        """
        Mock Gemini success response with JSON content.

        Gemini format is different from OpenAI/Anthropic.
        """
        return {
            "key": "test-123",
            "response": {
                "candidates": [
                    {"content": {"parts": [{"text": '{"answer": "4"}'}]}, "finish_reason": "STOP"}
                ],
                "usage_metadata": {
                    "prompt_token_count": 15,
                    "candidates_token_count": 10,
                    "total_token_count": 25,
                },
            },
        }

    @pytest.fixture
    def provider_success_response_string(self):
        """Mock Gemini success response with plain text."""
        return {
            "key": "test-456",
            "response": {
                "candidates": [
                    {"content": {"parts": [{"text": "Hello world"}]}, "finish_reason": "STOP"}
                ],
                "usage_metadata": {
                    "prompt_token_count": 12,
                    "candidates_token_count": 5,
                    "total_token_count": 17,
                },
            },
        }

    @pytest.fixture
    def provider_error_response(self):
        """Mock Gemini error response."""
        return {
            "key": "test-789",
            "error": {
                "code": 400,
                "message": "Invalid model specified",
                "status": "INVALID_ARGUMENT",
            },
        }

    def test_gemini_format_task_uses_key_not_custom_id(self, provider, sample_batch_task):
        """
        Gemini-specific: Verify task format uses 'key' not 'custom_id'.

        Gemini uses 'key' as the identifier field.
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "key" in result, "Gemini requires 'key' field"
        assert result["key"] == "test-123", "key should match custom_id"

    def test_gemini_format_task_uses_contents_structure(self, provider, sample_batch_task):
        """
        Gemini-specific: Verify task uses contents/parts structure.

        Gemini has unique nested structure for messages.
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert "request" in result, "Gemini requires 'request' field"
        assert "contents" in result["request"], "Gemini requires 'contents'"
        assert isinstance(result["request"]["contents"], list), "contents should be list"
        assert "parts" in result["request"]["contents"][0], "Gemini requires 'parts'"

    def test_gemini_format_task_with_schema_uses_response_schema(self, provider, sample_batch_task):
        """
        Gemini-specific: Verify schema is added as response_schema.

        Gemini has native schema support with response_schema field.
        """
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert "response_schema" in result["request"], "Gemini should use response_schema"
        assert "response_mime_type" in result["request"], "Gemini should set response_mime_type"
        assert result["request"]["response_mime_type"] == "application/json"

    def test_format_task_basic(self, provider, sample_batch_task):
        """Override: Gemini uses 'key' not 'custom_id'."""
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert isinstance(result, dict)
        assert "key" in result
        assert result["key"] == "test-123"

    def test_format_task_with_schema(self, provider, sample_batch_task):
        """Override: Gemini uses 'key' not 'custom_id'."""
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert isinstance(result, dict)
        assert "key" in result

    def test_format_task_no_max_tokens(self, provider, sample_batch_task_no_max_tokens):
        """Override: Gemini uses 'key' not 'custom_id'."""
        result = provider.format_task_for_provider(sample_batch_task_no_max_tokens, schema=None)
        assert isinstance(result, dict)
        assert "key" in result

    def test_prepare_tasks_json_mode_true(
        self, provider, sample_data, sample_agent_config_json_mode
    ):
        """Override: Gemini tasks use 'key' not 'custom_id'."""
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_json_mode)
        assert isinstance(tasks, list)
        assert len(tasks) == 3
        assert all("key" in task for task in tasks)

    def test_prepare_tasks_json_mode_false(
        self, provider, sample_data, sample_agent_config_no_json_mode
    ):
        """Override: Gemini tasks use 'key' not 'custom_id'."""
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)
        assert isinstance(tasks, list)
        assert len(tasks) == 3
        assert all("key" in task for task in tasks)

    def test_submit_and_retrieve_workflow(
        self, provider, tmp_path, sample_data, sample_agent_config_no_json_mode
    ):
        """Test submit and retrieve workflow with Gemini client."""
        # Prepare tasks
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)
        assert len(tasks) == 3

        # Submit batch
        batch_id = provider.submit_batch(tasks, str(tmp_path))
        assert batch_id is not None

    def test_retrieve_invalid_batch_id_raises_error(self, provider, tmp_path):
        """Test error handling for invalid batch ID."""
        from agent_actions.errors import VendorAPIError

        provider.client.batches.get.side_effect = VendorAPIError(
            vendor="gemini", endpoint="batches.get", context={"message": "Batch not found"}
        )
        with pytest.raises(VendorAPIError):
            provider.retrieve_results("nonexistent-batch-id", str(tmp_path))
