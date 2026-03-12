"""
Shared test suite for all BaseBatchClient implementations.

This module defines the contract that all batch clients must satisfy.
Every client (Ollama, OpenAI, Anthropic, Gemini) must pass these tests
to ensure consistent behavior across the system.

Design Pattern: Template Method Pattern
- Base class defines test logic (the "recipe")
- Subclasses provide client-specific fixtures (the "ingredients")
- pytest runs tests for each subclass automatically

Usage:
    class TestOllamaBatchClient(BaseBatchClientTests):
        @pytest.fixture
        def client(self):
            return OllamaBatchClient()

        @pytest.fixture
        def client_success_response_json(self):
            return {...}  # Client-specific response format

        # All 11 contract tests inherited automatically!

Contract Tests Overview:
    1. test_format_task_basic - Basic task formatting
    2. test_format_task_with_schema - Task formatting with JSON schema
    3. test_format_task_no_max_tokens - Task formatting without max_tokens
    4. test_parse_success_response_json - Parse success with JSON content
    5. test_parse_success_response_string - Parse success with string content
    6. test_parse_error_response - Parse error response
    7. test_prepare_tasks_json_mode_true - Prepare tasks with JSON mode
    8. test_prepare_tasks_json_mode_false - Prepare tasks without JSON mode
    9. test_check_status_returns_valid_state - Status check returns valid state
    10. test_submit_and_retrieve_workflow - Full end-to-end workflow
    11. test_retrieve_invalid_batch_id_raises_error - Error handling
"""

from abc import ABC, abstractmethod
from typing import Any

import pytest

from agent_actions.llm.providers.batch_base import (
    BaseBatchClient,
    BatchResult,
)


class BaseBatchClientTests(ABC):
    """
    Abstract base class for testing BaseBatchClient implementations.

    This class provides a comprehensive test suite that all batch clients
    must pass to ensure they correctly implement the BaseBatchClient interface
    and behave consistently.

    Subclass Requirements:
    - Must implement provider() fixture returning BaseBatchClient instance
    - Must implement 3 response fixtures (success_json, success_string, error)
    - Optionally override tests for client-specific behavior
    - Optionally add client-specific edge case tests
    """

    @pytest.fixture
    @abstractmethod
    def provider(self) -> BaseBatchClient:
        """
        Return an instance of the batch client to test.

        Example:
            @pytest.fixture
            def provider(self):
                return OllamaBatchClient(base_url="http://localhost:11434")
        """
        pass

    @pytest.fixture
    @abstractmethod
    def provider_success_response_json(self) -> dict[str, Any]:
        """
        Return a mock successful response with JSON content in provider format.

        Must include:
        - custom_id field
        - Success indicator (status_code, error field, etc.)
        - Content with parseable JSON string

        Example (Ollama/OpenAI format):
            {
                "custom_id": "test-123",
                "response": {
                    "status_code": 200,
                    "body": {
                        "choices": [{"message": {"content": '{"answer": "4"}'}}]
                    }
                },
                "error": None
            }
        """
        pass

    @pytest.fixture
    @abstractmethod
    def provider_success_response_string(self) -> dict[str, Any]:
        """
        Return a mock successful response with plain text content.

        Must include:
        - custom_id field
        - Success indicator
        - Content with plain string (not JSON)

        Example:
            {
                "custom_id": "test-456",
                "response": {
                    "status_code": 200,
                    "body": {
                        "choices": [{"message": {"content": "Hello world"}}]
                    }
                },
                "error": None
            }
        """
        pass

    @pytest.fixture
    @abstractmethod
    def provider_error_response(self) -> dict[str, Any]:
        """
        Return a mock error response in provider format.

        Must include:
        - custom_id field
        - Error indicator
        - Error message/details

        Example:
            {
                "custom_id": "test-789",
                "response": None,
                "error": {
                    "message": "Model not found",
                    "type": "invalid_request",
                    "code": "model_not_found"
                }
            }
        """
        pass

    def test_format_task_basic(self, provider, sample_batch_task):
        """
        Test basic task formatting without schema.

        Validates:
        - Method executes without errors
        - Returns a dict
        - Contains custom_id field
        - custom_id matches input
        """
        result = provider.format_task_for_provider(sample_batch_task, schema=None)
        assert isinstance(result, dict), "format_task_for_provider must return dict"
        assert "custom_id" in result, "Result must contain custom_id field"
        assert result["custom_id"] == "test-123", "custom_id must match input"

    def test_format_task_with_schema(self, provider, sample_batch_task):
        """
        Test task formatting with schema (JSON mode).

        Validates:
        - Method handles schema parameter
        - Returns valid dict structure
        - custom_id preserved
        """
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        result = provider.format_task_for_provider(sample_batch_task, schema=schema)
        assert isinstance(result, dict), "Must return dict even with schema"
        assert "custom_id" in result, "custom_id must be present with schema"
        assert result["custom_id"] == "test-123", "custom_id must match"

    def test_format_task_no_max_tokens(self, provider, sample_batch_task_no_max_tokens):
        """
        Test task formatting without max_tokens (Bug #2 validation).

        Validates:
        - Method handles missing max_tokens gracefully
        - Doesn't add max_tokens: null to output
        - Returns valid dict
        """
        result = provider.format_task_for_provider(sample_batch_task_no_max_tokens, schema=None)
        assert isinstance(result, dict), "Must handle missing max_tokens"
        assert "custom_id" in result, "custom_id must be present"

    def test_parse_success_response_json(self, provider, provider_success_response_json):
        """
        Test parsing successful response with JSON content.

        Validates:
        - Returns BatchResult object
        - success = True
        - content is parsed as dict (not string)
        - custom_id matches
        - error is None
        """
        result = provider.parse_provider_response(provider_success_response_json)
        assert isinstance(result, BatchResult), "Must return BatchResult"
        assert result.success == True, "Success response must have success=True"
        assert result.custom_id == "test-123", "custom_id must match response"
        assert result.error is None, "Successful response should have no error"
        assert isinstance(result.content, dict), "JSON content should be parsed as dict"
        assert "answer" in result.content, "Content should contain expected fields"

    def test_parse_success_response_string(self, provider, provider_success_response_string):
        """
        Test parsing successful response with plain text.

        Validates:
        - Returns BatchResult
        - success = True
        - content is string (not parsed as JSON)
        - custom_id matches
        """
        result = provider.parse_provider_response(provider_success_response_string)
        assert isinstance(result, BatchResult), "Must return BatchResult"
        assert result.success == True, "Success response must have success=True"
        assert result.custom_id == "test-456", "custom_id must match"
        assert isinstance(result.content, str), "Plain text should remain as string"
        assert result.error is None, "No error for successful response"

    def test_parse_error_response(self, provider, provider_error_response):
        """
        Test parsing error response.

        Validates:
        - Returns BatchResult
        - success = False
        - error field populated
        - custom_id preserved
        """
        result = provider.parse_provider_response(provider_error_response)
        assert isinstance(result, BatchResult), "Must return BatchResult even for errors"
        assert result.success == False, "Error response must have success=False"
        assert result.custom_id == "test-789", "custom_id must match error response"
        assert result.error is not None, "Error field must be populated"
        assert isinstance(result.error, str), "Error must be a string"
        assert len(result.error) > 0, "Error message must not be empty"

    def test_prepare_tasks_json_mode_true(
        self, provider, sample_data, sample_agent_config_json_mode
    ):
        """
        Test task preparation with json_mode: true.

        Validates:
        - All data rows converted to tasks
        - Each task has custom_id
        - Returns list of dicts
        - Schema passed when json_mode enabled
        """
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_json_mode)
        assert isinstance(tasks, list), "Must return list"
        assert len(tasks) == 3, "Must convert all data rows"
        assert all(isinstance(task, dict) for task in tasks), "All tasks must be dicts"
        assert all("custom_id" in task for task in tasks), "All tasks must have custom_id"
        custom_ids = [task["custom_id"] for task in tasks]
        assert "1" in custom_ids, "custom_id from target_id must be preserved"
        assert "2" in custom_ids
        assert "3" in custom_ids

    def test_prepare_tasks_json_mode_false(
        self, provider, sample_data, sample_agent_config_no_json_mode
    ):
        """
        Test task preparation with json_mode: false (Bug #4 validation).

        Validates:
        - All data rows converted
        - Schema NOT passed when json_mode disabled
        - Returns valid task format
        """
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)
        assert isinstance(tasks, list), "Must return list"
        assert len(tasks) == 3, "Must convert all data rows"
        assert all("custom_id" in task for task in tasks), "All tasks need custom_id"

    def test_check_status_returns_valid_state(self, provider):
        """
        Test status checking returns valid state.

        Validates:
        - Returns a string
        - String is one of valid batch states
        - Doesn't crash with arbitrary batch_id
        """
        status = provider.check_status("test-batch-id")
        assert isinstance(status, str), "Status must be a string"
        valid_states = [
            "validating",
            "in_progress",
            "completed",
            "failed",
            "expired",
            "cancelling",
            "cancelled",
        ]
        assert status in valid_states, f"Status '{status}' must be valid batch state"

    def test_submit_and_retrieve_workflow(
        self, provider, tmp_path, sample_data, sample_agent_config_no_json_mode
    ):
        """
        Integration test: Full batch workflow.

        Flow:
        1. Prepare tasks from data
        2. Submit batch
        3. Check status
        4. Retrieve results (if completed)
        5. Validate results

        Validates:
        - End-to-end workflow works
        - Files created (if applicable)
        - Results format correct
        - All BatchResult objects valid
        """
        tasks = provider.prepare_tasks(sample_data, sample_agent_config_no_json_mode)
        assert len(tasks) == 3, "Prepare step must create tasks"
        batch_id, initial_status = provider.submit_batch(
            tasks, "integration_test_batch", str(tmp_path)
        )
        assert batch_id is not None, "submit_batch must return batch_id"
        assert isinstance(batch_id, str), "batch_id must be string"
        assert len(batch_id) > 0, "batch_id must not be empty"
        assert isinstance(initial_status, str), "initial_status must be string"
        assert initial_status in [
            "completed",
            "in_progress",
            "validating",
            "submitted",
        ], f"Initial status must be valid: {initial_status}"
        status = provider.check_status(batch_id)
        assert status in [
            "completed",
            "in_progress",
            "validating",
        ], f"Status must be valid: {status}"
        if status == "completed":
            results = provider.retrieve_results(batch_id, str(tmp_path))
            assert isinstance(results, list), "Results must be a list"
            assert len(results) > 0, "Should have at least some results"
            assert all(isinstance(r, BatchResult) for r in results), (
                "All results must be BatchResult objects"
            )
            result_ids = [r.custom_id for r in results]
            assert len(result_ids) > 0, "Results must have custom_ids"

    def test_retrieve_invalid_batch_id_raises_error(self, provider, tmp_path):
        """
        Test that retrieving non-existent batch raises appropriate error.

        Validates:
        - Raises an exception (VendorAPIError or similar)
        - Doesn't crash with undefined behavior
        - Error message is meaningful
        """
        with pytest.raises(Exception) as exc_info:
            provider.retrieve_results("nonexistent-batch-id-12345", str(tmp_path))
        error_str = str(exc_info.value).lower()
        assert "batch" in error_str or "not found" in error_str or "file" in error_str, (
            "Error message should indicate batch/file not found"
        )
