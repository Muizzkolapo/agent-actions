"""
Reusable mixins for vendor handlers to reduce code duplication.

This module provides common functionality that multiple vendor handlers share,
eliminating duplicate code across different provider implementations.
"""

import logging
from typing import Any

from agent_actions.errors import VendorAPIError
from agent_actions.llm.providers.error_wrapper import NoAnswer, chat_no_answer, is_truncated
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.llm_events import LLMJSONParseErrorEvent

logger = logging.getLogger(__name__)


class JSONResponseMixin:
    """Mixin providing standardized JSON response parsing with error handling.

    Returns an error dict on parse failure rather than raising, leaving the
    caller to decide whether to regenerate. This is appropriate for providers
    with variable JSON quality (Groq, Gemini, Cohere).
    """

    @staticmethod
    def parse_json_response(
        response_content: str,
        vendor_name: str,
        operation: str,
        model_name: str,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Parse JSON response with code-fence stripping and repair support.

        Uses the shared :func:`parse_llm_json` utility (strips markdown
        fences, tries ``json_repair``) before falling back to a
        ``_parse_error`` dict.

        Args:
            response_content: Raw JSON string from API
            vendor_name: Name of vendor (for error messages)
            operation: Operation name (e.g., "call_json", "call_non_json")
            model_name: Model name (for logging)

        Returns:
            Parsed JSON data (dict or list), or error dict on parse failure
        """
        if not response_content:
            logger.warning(
                "%s returned empty response",
                vendor_name,
                extra={"operation": f"{vendor_name}_{operation}", "model": model_name},
            )
            return [{"raw_response": "", "_parse_error": "Empty response from API"}]

        from agent_actions.utils.json_parsing import parse_llm_json

        result = parse_llm_json(response_content)
        if not isinstance(result, str):
            logger.debug(
                "%s JSON response parsed successfully",
                vendor_name,
                extra={
                    "operation": f"{vendor_name}_{operation}",
                    "model": model_name,
                    "response_length": len(response_content),
                },
            )
            return result  # type: ignore[return-value]

        # All parse strategies failed — return an error dict the repair loop can act on
        logger.warning(
            "%s returned unparseable JSON, returning error dict for repair",
            vendor_name,
            extra={
                "operation": f"{vendor_name}_{operation}",
                "model": model_name,
                "response_text": response_content[:200],
            },
        )
        fire_event(
            LLMJSONParseErrorEvent(
                provider=vendor_name.lower(),
                model=model_name,
                error="Failed to parse JSON after all strategies",
            )
        )
        return [
            {
                "raw_response": response_content,
                "_parse_error": "Failed to parse JSON from LLM response",
            }
        ]


class GenericErrorHandlerMixin:
    """Mixin providing standardized generic error handling for vendor API calls."""

    @staticmethod
    def handle_generic_error(
        error: Exception,
        vendor_name: str,
        operation: str,
        model_name: str,
    ) -> None:
        """
        Handle generic exceptions with standardized logging and re-raising.

        Args:
            error: The caught exception
            vendor_name: Name of vendor
            operation: Operation name
            model_name: Model name

        Raises:
            VendorAPIError: Always raises with proper context
        """
        logger.error(
            "%s API call failed",
            vendor_name,
            extra={
                "operation": f"{vendor_name}_{operation}",
                "model": model_name,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )
        raise VendorAPIError(
            f"{vendor_name} API call failed ({operation}): {error}",
            vendor=vendor_name,
            cause=error,
        ) from error


class OpenAICompatibleResponseMixin:
    """
    Mixin for providers that use OpenAI-compatible response format.

    Provides standard extraction methods for error, content, metadata, and usage
    from OpenAI-style batch responses.
    """

    # The vendor as its online client names it in an empty-response error.
    _vendor_label = "OpenAI"

    def _extract_error_from_response(self, raw_response: dict[str, Any]) -> str | None:
        """Extract error from OpenAI-compatible response."""
        if raw_response.get("error"):
            return str(raw_response["error"])
        response_data = raw_response.get("response", {})
        status_code = response_data.get("status_code")
        if status_code and status_code != 200:
            body = response_data.get("body")
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            return f"HTTP {status_code}: {message}" if message else f"HTTP {status_code}"
        return None

    @staticmethod
    def _first_choice(raw_response: dict[str, Any]) -> dict[str, Any]:
        body = (raw_response.get("response") or {}).get("body") or {}
        return (body.get("choices") or [{}])[0] or {}

    def _no_answer(self, raw_response: dict[str, Any]) -> NoAnswer | None:
        """A refusal, or a message with no content, ended by the online client's ``chat_no_answer``."""
        choice = self._first_choice(raw_response)
        message = choice.get("message") or {}
        body = (raw_response.get("response") or {}).get("body") or {}
        return chat_no_answer(
            message.get("content"),
            choice.get("finish_reason"),
            message.get("refusal"),
            vendor_label=self._vendor_label,
            model_name=body.get("model") or "",
            vendor=self._vendor_label.lower(),
        )

    def _answer_was_cut_off(self, raw_response: dict[str, Any]) -> bool:
        return is_truncated(self._first_choice(raw_response).get("finish_reason"))

    def _extract_error_status(self, raw_response: dict[str, Any]) -> int | None:
        """The status of the line's response; None for a line that failed before any request."""
        response_data = raw_response.get("response")
        status_code = response_data.get("status_code") if isinstance(response_data, dict) else None
        return status_code if isinstance(status_code, int) and status_code != 200 else None

    def _extract_content_from_response(self, raw_response: dict[str, Any]) -> Any:
        """Extract content from OpenAI-compatible response."""
        response_data = raw_response.get("response", {})
        response_body = response_data.get("body", {})
        if "choices" in response_body and response_body["choices"]:
            choice = response_body["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"]
        return None

    def _extract_metadata_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from OpenAI-compatible response."""
        response_data = raw_response.get("response", {})
        response_body = response_data.get("body", {})
        # Safely extract finish_reason from choices array
        choices = response_body.get("choices", [{}])
        finish_reason = choices[0].get("finish_reason") if choices else None
        return {
            "model": response_body.get("model"),
            "finish_reason": finish_reason,
            "status_code": response_data.get("status_code"),
        }

    def _extract_usage_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any] | None:
        """Extract usage from OpenAI-compatible response."""
        response_data = raw_response.get("response", {})
        response_body = response_data.get("body", {})
        return response_body.get("usage")  # type: ignore[no-any-return]
