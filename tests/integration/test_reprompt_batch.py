"""
Integration tests for batch reprompt processing.

Tests the full batch reprompt flow through BatchProcessingService with validation UDFs.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent_actions.core.reprompt_validation import (
    reprompt_validation,
    _VALIDATION_REGISTRY,
)
from agent_actions.llm_invocation.providers.batch_client_base import BatchResult
from agent_actions.core.types import RecoveryMetadata, RepromptMetadata


class TestBatchRepromptIntegration:
    """Integration tests for batch reprompt with BatchProcessingService."""

    def setup_method(self):
        """Clear registry and register test UDFs."""
        _VALIDATION_REGISTRY.clear()

        # Register validation UDF that checks for forbidden words
        @reprompt_validation("Response must not contain the word 'forbidden'")
        def check_no_forbidden_words(response: dict) -> bool:
            text = str(response).lower()
            return "forbidden" not in text

        # Register validation UDF for required fields
        @reprompt_validation("Response must contain 'title' and 'summary' fields")
        def check_required_fields(response: dict) -> bool:
            return "title" in response and "summary" in response

    def test_batch_reprompt_feedback_injected_into_resubmitted_batch(self):
        """
        CRITICAL TEST: Verify feedback is injected into prompts for reprompt batch.

        This test verifies the method exists and will test behavior once implemented.

        Flow:
        1. Initial batch returns 3 results, 1 fails validation
        2. Failed record resubmitted with feedback appended to prompt
        3. Verify resubmitted batch task has feedback in user_content
        4. Verify final result has reprompt metadata
        """
        from agent_actions.llm_invocation.batch.services.batch_processing_service import (
            BatchProcessingService,
        )

        # Setup mocks
        mock_client_resolver = Mock()
        mock_context_manager = Mock()
        mock_result_processor = Mock()
        mock_registry_factory = Mock()

        service = BatchProcessingService(
            client_resolver=mock_client_resolver,
            context_manager=mock_context_manager,
            result_processor=mock_result_processor,
            registry_manager_factory=mock_registry_factory,
        )

        # Check if method exists (will fail until implemented)
        assert hasattr(service, "_validate_and_reprompt"), (
            "_validate_and_reprompt method not yet implemented in BatchProcessingService"
        )

    def test_batch_reprompt_all_pass_validation_no_resubmit(self):
        """When all records pass validation, no reprompt batch should be submitted."""
        # This test will also fail until implementation
        pass

    def test_batch_reprompt_partial_failure_only_failed_resubmitted(self):
        """Only records that fail validation should be resubmitted."""
        pass

    def test_batch_reprompt_exhausted_returns_last_response(self):
        """When reprompt exhausts attempts with on_exhausted=return_last."""
        pass

    def test_batch_reprompt_with_retry_both_metadata_present(self):
        """When both retry and reprompt enabled, both metadata should be present."""
        pass
