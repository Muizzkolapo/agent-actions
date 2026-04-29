"""Batch processing and LLM provider edge cases.

1. _create_exhausted_item() — action_name validation
2. _submit_to_provider() — ExternalServiceError wrapping
3. Cohere/Mistral token extraction — nullable token values
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ExternalServiceError
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

# Patch targets:
# - set_last_usage and fire_event (LLMResponseEvent) now live in response_builder
# - fire_event (LLMRequestEvent/LLMErrorEvent) still in each provider client
_RB = "agent_actions.output.response.response_builder"

# =============================================================================
# 1. _create_exhausted_item() — action_name propagation
# =============================================================================


class TestCreateExhaustedItemActionName:
    """_create_exhausted_item must pass action_name to ExhaustedRecordBuilder."""

    def test_action_name_propagated_from_agent_config(self):
        """action_name from agent_config flows into the exhausted item's node_id."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config={"action_name": "classify_sentiment"},
        )
        ctx.reconciler = MagicMock()
        ctx.reconciler.get_source_guid.return_value = "sg-123"

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="api_error")
        )
        processor = BatchResultStrategy()

        item = processor._create_exhausted_item(ctx, "custom-1", {"text": "hello"}, recovery)

        # node_id is generated from action_name — verify it contains the action name
        assert item["node_id"].startswith("classify_sentiment_")
        assert item["source_guid"] == "sg-123"
        assert item["metadata"]["retry_exhausted"] is True
        assert item["_unprocessed"] is True

    def test_action_name_missing_raises(self):
        """When agent_config has no action_name, RecordEnvelopeError is raised (empty names are banned)."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.record.envelope import RecordEnvelopeError

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config={"model_vendor": "openai"},  # no action_name
        )
        ctx.reconciler = MagicMock()
        ctx.reconciler.get_source_guid.return_value = "sg-456"

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=2, succeeded=False, reason="timeout")
        )
        processor = BatchResultStrategy()

        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            processor._create_exhausted_item(ctx, "custom-2", {"text": "world"}, recovery)

    def test_action_name_missing_when_agent_config_is_none_raises(self):
        """When agent_config is None, RecordEnvelopeError is raised (empty names are banned)."""
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.record.envelope import RecordEnvelopeError

        ctx = BatchProcessingContext(
            batch_results=[],
            context_map={},
            output_directory=None,
            agent_config=None,
        )
        ctx.reconciler = MagicMock()
        ctx.reconciler.get_source_guid.return_value = "sg-789"

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=1, failures=1, succeeded=False, reason="network_error")
        )
        processor = BatchResultStrategy()

        with pytest.raises(RecordEnvelopeError, match="action_name is required"):
            processor._create_exhausted_item(ctx, "custom-3", {"text": "data"}, recovery)


# =============================================================================
# 2. _submit_to_provider() — ExternalServiceError constructor
# =============================================================================


class TestSubmitToProviderErrorPath:
    """_submit_to_provider wraps provider errors in ExternalServiceError with correct structure."""

    def test_provider_error_produces_external_service_error(self):
        """Provider exception is wrapped with message, context, and cause."""
        from agent_actions.llm.batch.services.submission import BatchSubmissionService

        client_resolver = MagicMock()
        provider = MagicMock()
        provider.submit_batch.side_effect = RuntimeError("Connection refused")
        client_resolver.get_for_config.return_value = provider

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        with patch("agent_actions.llm.batch.services.submission.fire_event"):
            with pytest.raises(ExternalServiceError) as exc_info:
                service._submit_to_provider(
                    agent_config={"model_vendor": "openai"},
                    batch_name="test",
                    tasks=[{"id": "1"}],
                    output_directory=None,
                )

        err = exc_info.value
        assert "Failed to submit batch job" in str(err)
        assert err.context["vendor"] == "openai"
        assert err.cause is not None
        assert isinstance(err.cause, RuntimeError)

    def test_provider_error_fires_failure_event(self):
        """Provider exception fires BatchSubmissionFailedEvent before raising."""
        from agent_actions.llm.batch.services.submission import BatchSubmissionService

        client_resolver = MagicMock()
        provider = MagicMock()
        provider.submit_batch.side_effect = RuntimeError("timeout")
        client_resolver.get_for_config.return_value = provider

        service = BatchSubmissionService(
            task_preparator=MagicMock(),
            client_resolver=client_resolver,
            context_manager=MagicMock(),
            registry_manager_factory=MagicMock(),
        )

        fired = []
        with patch(
            "agent_actions.llm.batch.services.submission.fire_event",
            side_effect=lambda e: fired.append(e),
        ):
            with pytest.raises(ExternalServiceError):
                service._submit_to_provider(
                    agent_config={"model_vendor": "gemini"},
                    batch_name="test",
                    tasks=[{"id": "1"}],
                    output_directory=None,
                )

        from agent_actions.logging.events.batch_events import (
            BatchSubmissionFailedEvent,
        )

        failed_events = [e for e in fired if isinstance(e, BatchSubmissionFailedEvent)]
        assert len(failed_events) == 1
        assert failed_events[0].provider == "gemini"
        assert "timeout" in failed_events[0].error


# =============================================================================
# 3. Cohere/Mistral token extraction — nullable token values
# =============================================================================


class TestCohereNullableTokens:
    """Cohere client token extraction handles None token values via or 0."""

    def test_none_input_tokens_defaults_to_zero(self):
        """When tokens.input_tokens is None, prompt_tokens defaults to 0.

        Exercises the ``or 0`` coercion in ResponseBuilder._extract_cohere().
        Because all tokens are zero, ``set_last_usage`` is intentionally
        skipped; we verify the coercion via ``extract_usage`` directly.
        """
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text='{"result": "ok"}')]
        mock_response.usage.tokens.input_tokens = None
        mock_response.usage.tokens.output_tokens = None

        with (
            patch("agent_actions.llm.providers.cohere.client.cohere") as mock_cohere,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.cohere.client.fire_event"),
        ):
            mock_cohere.ClientV2.return_value.chat.return_value = mock_response

            from agent_actions.llm.providers.cohere.client import CohereClient

            CohereClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "command-r-plus"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "cohere")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0

    def test_valid_tokens_pass_through(self):
        """When tokens have valid int values, they pass through unchanged."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text='{"result": "ok"}')]
        mock_response.usage.tokens.input_tokens = 100
        mock_response.usage.tokens.output_tokens = 50

        with (
            patch("agent_actions.llm.providers.cohere.client.cohere") as mock_cohere,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.cohere.client.fire_event"),
        ):
            mock_cohere.ClientV2.return_value.chat.return_value = mock_response

            from agent_actions.llm.providers.cohere.client import CohereClient

            CohereClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "command-r-plus"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        usage_dict = mock_usage.call_args[0][0]
        assert usage_dict["input_tokens"] == 100
        assert usage_dict["output_tokens"] == 50

    def test_none_usage_object_skips_set_last_usage(self):
        """When response.usage is None (no usage attr), set_last_usage is not called."""
        mock_response = MagicMock(spec=[])  # no attributes by default
        mock_response.message = MagicMock()
        mock_response.message.content = [MagicMock(text='{"result": "ok"}')]
        # response has no 'usage' attribute — hasattr(response, "usage") is False

        with (
            patch("agent_actions.llm.providers.cohere.client.cohere") as mock_cohere,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.cohere.client.fire_event"),
        ):
            mock_cohere.ClientV2.return_value.chat.return_value = mock_response

            from agent_actions.llm.providers.cohere.client import CohereClient

            CohereClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "command-r-plus"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        mock_usage.assert_not_called()

    def test_none_input_tokens_defaults_to_zero_call_non_json(self):
        """call_non_json: None token values default to 0 via ``or 0``.

        Same as call_json — coercion verified via ``extract_usage``;
        ``set_last_usage`` is skipped for all-zero usage.
        """
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text="plain text response")]
        mock_response.usage.tokens.input_tokens = None
        mock_response.usage.tokens.output_tokens = None

        with (
            patch("agent_actions.llm.providers.cohere.client.cohere") as mock_cohere,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.cohere.client.fire_event"),
        ):
            mock_cohere.ClientV2.return_value.chat.return_value = mock_response

            from agent_actions.llm.providers.cohere.client import CohereClient

            CohereClient.call_non_json(
                api_key="test-key",
                agent_config={"model_name": "command-r-plus"},
                prompt_config="test prompt",
                context_data="test data",
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "cohere")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0


class TestMistralNullableTokens:
    """Mistral client token extraction handles None token values via or 0."""

    def test_none_usage_tokens_default_to_zero(self):
        """When usage token fields are None, they default to 0.

        The ``or 0`` coercion in ResponseBuilder._extract_openai_compat()
        converts None to 0.  Because all tokens are zero, ``set_last_usage``
        is intentionally skipped; we verify the coercion via ``extract_usage``.
        """
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"result": "ok"}'
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = None
        mock_response.usage.completion_tokens = None
        mock_response.usage.total_tokens = None

        with (
            patch("agent_actions.llm.providers.mistral.client.Mistral") as mock_mistral,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.mistral.client.fire_event"),
        ):
            mock_mistral.return_value.chat.complete.return_value = mock_response

            from agent_actions.llm.providers.mistral.client import MistralClient

            MistralClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "mistral-large-latest"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "mistral")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_none_usage_object_defaults_to_zero(self):
        """When usage object itself is None, token values default to 0."""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"result": "ok"}'
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        with (
            patch("agent_actions.llm.providers.mistral.client.Mistral") as mock_mistral,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.mistral.client.fire_event"),
        ):
            mock_mistral.return_value.chat.complete.return_value = mock_response

            from agent_actions.llm.providers.mistral.client import MistralClient

            # Should not crash — or 0 handles None usage
            result = MistralClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "mistral-large-latest"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        assert result is not None
        mock_usage.assert_not_called()

    def test_none_usage_tokens_default_to_zero_call_non_json(self):
        """call_non_json: None token fields default to 0.

        Same as call_json — coercion verified via ``extract_usage``;
        ``set_last_usage`` is skipped for all-zero usage.
        """
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "plain text response"
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = None
        mock_response.usage.completion_tokens = None
        mock_response.usage.total_tokens = None

        with (
            patch("agent_actions.llm.providers.mistral.client.Mistral") as mock_mistral,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch("agent_actions.llm.providers.mistral.client.fire_event"),
        ):
            mock_mistral.return_value.chat.complete.return_value = mock_response

            from agent_actions.llm.providers.mistral.client import MistralClient

            MistralClient.call_non_json(
                api_key="test-key",
                agent_config={"model_name": "mistral-large-latest"},
                prompt_config="test prompt",
                context_data="test data",
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "mistral")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
