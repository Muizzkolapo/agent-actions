"""Regression tests for Gemini client nullable token count handling.

Mirrors TestCohereNullableTokens and TestMistralNullableTokens in
test_pr1108_bugfix_regressions.py. Exercises the `or 0` coercion
when usage_metadata fields are None.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.output.response.response_builder import ResponseBuilder

# Patch targets:
# - set_last_usage and fire_event (LLMResponseEvent) now live in response_builder
# - fire_event (LLMRequestEvent/LLMErrorEvent) still in gemini.client
_RB = "agent_actions.output.response.response_builder"
_GC = "agent_actions.llm.providers.gemini.client"


class TestGeminiNullableTokens:
    """Gemini client token extraction handles None token values via or 0."""

    def test_none_token_counts_default_to_zero(self):
        """When usage_metadata token fields are None, they default to 0.

        The ResponseBuilder's ``or 0`` coercion converts None to 0.
        Because all tokens are zero, ``set_last_usage`` is intentionally
        skipped by the guard in ``record_usage_and_event``; we verify
        the coercion via ``extract_usage`` directly.
        """
        mock_response = MagicMock()
        mock_response.text = '{"result": "ok"}'
        mock_response.usage_metadata.prompt_token_count = None
        mock_response.usage_metadata.candidates_token_count = None
        mock_response.usage_metadata.total_token_count = None

        with (
            patch(f"{_GC}._build_client") as mock_build,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch(f"{_GC}.fire_event"),
        ):
            mock_build.return_value.models.generate_content.return_value = mock_response

            GeminiClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "gemini-2.0-flash"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "gemini")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_valid_token_counts_pass_through(self):
        """When usage_metadata has valid int values, they pass through unchanged."""
        mock_response = MagicMock()
        mock_response.text = '{"result": "ok"}'
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 50
        mock_response.usage_metadata.total_token_count = 150

        with (
            patch(f"{_GC}._build_client") as mock_build,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch(f"{_GC}.fire_event"),
        ):
            mock_build.return_value.models.generate_content.return_value = mock_response

            GeminiClient.call_json(
                api_key="test-key",
                agent_config={"model_name": "gemini-2.0-flash"},
                prompt_config="test prompt",
                context_data="test data",
                schema={"properties": {"result": {"type": "string"}}},
            )

        usage_dict = mock_usage.call_args[0][0]
        assert usage_dict["input_tokens"] == 100
        assert usage_dict["output_tokens"] == 50
        assert usage_dict["total_tokens"] == 150

    def test_none_token_counts_call_non_json(self):
        """call_non_json: None token fields default to 0.

        Same logic as call_json — ``or 0`` coercion is verified via
        ``extract_usage``; ``set_last_usage`` is skipped for all-zero usage.
        """
        mock_response = MagicMock()
        mock_response.text = "plain text response"
        mock_response.usage_metadata.prompt_token_count = None
        mock_response.usage_metadata.candidates_token_count = None
        mock_response.usage_metadata.total_token_count = None

        with (
            patch(f"{_GC}._build_client") as mock_build,
            patch(f"{_RB}.set_last_usage") as mock_usage,
            patch(f"{_RB}.fire_event"),
            patch(f"{_GC}.fire_event"),
        ):
            mock_build.return_value.models.generate_content.return_value = mock_response

            GeminiClient.call_non_json(
                api_key="test-key",
                agent_config={"model_name": "gemini-2.0-flash"},
                prompt_config="test prompt",
                context_data="test data",
            )

        # All tokens are zero after coercion — set_last_usage is skipped
        mock_usage.assert_not_called()

        # Verify the or-0 coercion via extract_usage directly
        usage = ResponseBuilder.extract_usage(mock_response, "gemini")
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
