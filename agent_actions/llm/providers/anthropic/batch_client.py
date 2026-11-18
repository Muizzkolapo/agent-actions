"""
Anthropic Batch API client implementation.
"""

import json
import logging
from pathlib import Path
from typing import Any

from agent_actions.llm.providers.anthropic import PROMPT_CACHING_BETA_HEADER, server_busy_errors
from agent_actions.llm.providers.error_wrapper import empty_response_error, is_truncated
from agent_actions.prompt.cache_scope import prompt_is_shared
from agent_actions.prompt.message_builder import MessageBuilder
from agent_actions.utils.atomic_write import atomic_json_write

from ..batch_base import BaseBatchClient, BatchTask

logger = logging.getLogger(__name__)


# The HTTP status of each error type the Anthropic API names in an error response.
_ERROR_TYPE_STATUS = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "billing_error": 402,
    "permission_error": 403,
    "not_found_error": 404,
    "request_too_large": 413,
    "rate_limit_error": 429,
    "api_error": 500,
    "timeout_error": 504,
    "overloaded_error": 529,
}


class AnthropicBatchClient(BaseBatchClient):
    """
    Anthropic Message Batches API implementation of the BaseBatchClient interface.

    This provider integrates with Anthropic's Message Batches API to enable
    batch processing of Claude model requests. It handles format transformations:
    - Input: BatchTask → Anthropic batch request format with custom_id and params
    - Output: Anthropic batch response → BatchResult

    Supports all Claude models available through the Message Batches API including:
    - Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus, etc.

    Features:
    - Real-time batch status checking
    - Structured response parsing
    - Proper error handling for API failures
    - Support for prompt caching (when enabled)
    """

    def __init__(
        self,
        api_key: str | None = None,
        enable_prompt_caching: bool = False,
    ):
        """
        Initialize Anthropic client with optional configuration.

        Args:
            api_key: Anthropic API key
            enable_prompt_caching: Whether to enable prompt caching feature
        """
        self.enable_prompt_caching = enable_prompt_caching
        try:
            import anthropic

            self.anthropic = anthropic
            self._transient_errors = (
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
                *server_busy_errors(anthropic),
            )
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)
            else:
                self.client = anthropic.Anthropic()
        except ImportError as e:
            from agent_actions.errors import (
                ConfigurationError,
            )

            raise ConfigurationError(
                "Required package not installed",
                context={"package": "anthropic", "install_command": "uv pip install anthropic"},
                cause=e,
            ) from e
        except Exception as e:
            from agent_actions.errors import (
                ConfigurationError,
            )

            raise ConfigurationError(
                "Failed to initialize Anthropic client",
                context={
                    "provider": "anthropic",
                    "error": str(e),
                    "api_key_source": "environment variable or parameter",
                },
                cause=e,
            ) from e

    def _caches_prompt(self, agent_config: dict[str, Any]) -> bool:
        return self.enable_prompt_caching and prompt_is_shared(agent_config)

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Transform our BatchTask to Anthropic's Message Batches API format.

        Anthropic Message Batches API expects:
        {
            "custom_id": "my-first-request",
            "params": {
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": "Hello, world"}
                ]
            }
        }
        """
        envelope = MessageBuilder.build_for_batch(
            "anthropic",
            batch_task.prompt,
            batch_task.user_content,
            schema=schema,
            enable_prompt_caching=batch_task.cache_prompt,
            shared_prompt_len=batch_task.shared_prompt_len,
        )
        # Anthropic batch: system is a top-level param, user content is the message
        params = {
            "model": batch_task.model_config.get("model_name", self._get_default_model()),
            "messages": envelope.to_dicts(role="user"),
        }
        if any(m.content for m in envelope.messages if m.role == "system"):
            params["system"] = envelope.to_dicts(role="system")[0]["content"]
        self._add_optional_param(params, "temperature", batch_task.model_config.get("temperature"))
        self._add_optional_param(
            params, "max_tokens", batch_task.model_config.get("max_tokens"), default=4096
        )
        params.update(
            self._sampling_params(
                batch_task.model_config, key_map={"stop": "stop_sequences"}, stop_as_list=True
            )
        )
        from agent_actions.llm.providers.anthropic.client import AnthropicClient

        vendor_params = batch_task.model_config.get("vendor_params") or {}
        # The compiled schema is the tool, offered and not forced, as online sends it.
        if schema:
            params["tools"] = schema
        AnthropicClient.VENDOR_PARAMS.apply_to_body(params, vendor_params)
        return {"custom_id": batch_task.custom_id, "params": params}

    def _extract_error_from_response(self, raw_response: Any) -> str | None:
        """Extract error from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        if result is None:
            return "Invalid response format from Anthropic"

        result_type = self._get_attribute_or_key(result, "type")
        if result_type == "succeeded":
            return self._no_answer_error(result)
        if result_type == "errored":
            error_info = self._get_attribute_or_key(result, "error", {})
            return str(error_info) if error_info else "Batch processing errored"
        if result_type == "expired":
            return "Batch result expired before processing"
        if result_type == "canceled":
            return "Batch result was canceled"
        return f"Unknown result type: {result_type}"

    def _extract_error_status(self, raw_response: Any) -> int | None:
        """The HTTP status of an errored result's error type; None for an expired or canceled one."""
        result = self._get_attribute_or_key(raw_response, "result")
        error = self._get_attribute_or_key(result, "error")
        # An errored result holds the API's error response: {type: error, error: {type, message}}.
        inner = self._get_attribute_or_key(error, "error") or error
        return _ERROR_TYPE_STATUS.get(self._get_attribute_or_key(inner, "type"))

    def _no_answer_error(self, result: Any) -> str | None:
        """The error for a message whose blocks hold no text or tool answer, as online raises.

        A thinking block alone (max_tokens spent while thinking) is not the answer. An
        empty content list is left to the action's ``on_empty``.
        """
        message = self._get_attribute_or_key(result, "message", {})
        content_list = self._get_attribute_or_key(message, "content", [])
        if not isinstance(content_list, list) or not content_list:
            return None
        if self._extract_tool_use_content(content_list) is not None:
            return None
        if self._extract_text_content(content_list) is not None:
            return None
        error = empty_response_error(
            "Anthropic",
            self._get_attribute_or_key(message, "stop_reason"),
            model_name=self._get_attribute_or_key(message, "model") or "",
            vendor="anthropic",
            operation="messages.batches",
        )
        return str(error)

    def _answer_was_cut_off(self, raw_response: Any) -> bool:
        result = self._get_attribute_or_key(raw_response, "result")
        message = self._get_attribute_or_key(result, "message", {})
        return is_truncated(self._get_attribute_or_key(message, "stop_reason"))

    def _extract_content_from_response(self, raw_response: Any) -> Any:
        """Extract content from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        message = self._get_attribute_or_key(result, "message", {})
        content_list = self._get_attribute_or_key(message, "content", [])
        # Cut-off text stays as written; a tool answer is read as online reads it.
        cut_off = self._answer_was_cut_off(raw_response) and isinstance(content_list, list)
        if cut_off and self._extract_tool_use_content(content_list) is None:
            text = self._extract_text_content(content_list)
            if text is not None:
                return text
        return self._parse_content_list(content_list)

    def _answer_text(self, raw_response: Any) -> str | None:
        result = self._get_attribute_or_key(raw_response, "result")
        message = self._get_attribute_or_key(result, "message", {})
        content_list = self._get_attribute_or_key(message, "content", [])
        if (
            not isinstance(content_list, list)
            or self._extract_tool_use_content(content_list) is not None
        ):
            return None
        return self._extract_text_content(content_list)

    def _parse_content_list(self, content_list: Any) -> Any:
        """
        Parse Anthropic content list, prioritizing tool use over text.

        Complexity reduced by breaking into smaller helper methods.
        """
        if not content_list or not isinstance(content_list, list):
            return content_list

        # First pass: look for tool use (structured output)
        tool_use_content = self._extract_tool_use_content(content_list)
        if tool_use_content is not None:
            logger.debug("Extracted structured JSON from tool use")
            logger.debug("Tool content type: %s", type(tool_use_content))
            if isinstance(tool_use_content, dict):
                logger.debug("Tool content keys: %s", list(tool_use_content.keys()))
            return tool_use_content

        # Second pass: look for text content
        text_content = self._extract_text_content(content_list)
        if text_content is not None:
            logger.debug("Got text response: %s...", text_content[:100])
            parsed = self._parse_json_content(text_content)
            if isinstance(parsed, dict):
                logger.debug("Successfully parsed text as JSON")
            return parsed

        # Fallback: try first item
        return self._fallback_content_extraction(content_list[0])

    def _extract_tool_use_content(self, content_list: list) -> Any | None:
        """Extract content from tool_use blocks."""
        for content_block in content_list:
            # Check object with type='tool_use'
            if hasattr(content_block, "type") and content_block.type == "tool_use":
                tool_name = getattr(content_block, "name", "")
                if hasattr(content_block, "input"):
                    logger.debug("Found tool use: %s", tool_name)
                    tool_content = content_block.input
                    if hasattr(tool_content, "model_dump"):
                        return tool_content.model_dump()
                    return tool_content

            # Check dict with type='tool_use'
            elif isinstance(content_block, dict) and content_block.get("type") == "tool_use":
                tool_name = content_block.get("name", "")
                logger.debug("Found tool use: %s", tool_name)
                return content_block.get("input", {})

        return None

    def _extract_text_content(self, content_list: list) -> str | None:
        """Extract text from text blocks."""
        for content_block in content_list:
            # Check object with type='text'
            if hasattr(content_block, "type") and content_block.type == "text":
                return self._get_attribute_or_key(content_block, "text")  # type: ignore[no-any-return]

            # Check dict with type='text'
            if isinstance(content_block, dict) and content_block.get("type") == "text":
                return content_block.get("text", "")  # type: ignore[no-any-return]

            # Check for text attribute/key directly
            text = self._get_attribute_or_key(content_block, "text")
            if text:
                return text  # type: ignore[no-any-return]

        return None

    def _fallback_content_extraction(self, content_item: Any) -> Any:
        """Fallback extraction for edge cases."""
        # Check for tool_use via type + input attributes
        if hasattr(content_item, "type") and hasattr(content_item, "input"):
            if content_item.type == "tool_use":
                logger.warning(
                    "Found uncaught tool use: %s", getattr(content_item, "name", "unknown")
                )
                content = content_item.input
                if hasattr(content, "model_dump"):
                    return content.model_dump()
                return content

        # Check for text attribute
        text = self._get_attribute_or_key(content_item, "text")
        if text:
            return self._parse_json_content(text)

        # Check class name for ToolUseBlock
        class_name = content_item.__class__.__name__ if hasattr(content_item, "__class__") else ""
        if "ToolUseBlock" in class_name:
            logger.warning("Found ToolUseBlock via class name check")
            if hasattr(content_item, "input"):
                content = content_item.input
                if hasattr(content, "model_dump"):
                    return content.model_dump()
                return content

        # Last resort: stringify
        return str(content_item)

    def _extract_metadata_from_response(self, raw_response: Any) -> dict[str, Any]:
        """Extract metadata from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        result_type = self._get_attribute_or_key(result, "type")
        message = self._get_attribute_or_key(result, "message", {})

        return {
            "model": self._get_attribute_or_key(message, "model"),
            "stop_reason": self._get_attribute_or_key(message, "stop_reason"),
            "result_type": result_type,
        }

    def _extract_usage_from_response(self, raw_response: Any) -> dict[str, Any] | None:
        """Extract usage from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        message = self._get_attribute_or_key(result, "message", {})
        usage = self._get_attribute_or_key(message, "usage")

        if usage and hasattr(usage, "model_dump"):
            return usage.model_dump()  # type: ignore[no-any-return]
        return usage  # type: ignore[no-any-return]

    def _get_default_model(self) -> str:
        """Return Anthropic's default model."""
        return "claude-sonnet-4-6"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSON file for Anthropic."""
        file_name = f"{Path(batch_name).stem}_anthropic_batch_input.json"
        file_path = batch_dir / file_name
        atomic_json_write(file_path, {"requests": tasks}, indent=2, fsync=False)
        logger.info("Anthropic batch input saved at: %s", file_path)
        return file_path

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit batch to Anthropic API."""
        try:
            # Read tasks from file to submit
            with open(input_file, encoding="utf-8") as f:
                data = json.load(f)
                tasks = data["requests"]

            batch_response = self.client.messages.batches.create(
                requests=tasks,
                extra_headers=PROMPT_CACHING_BETA_HEADER if self.enable_prompt_caching else None,
            )
            batch_id = batch_response.id
            status = batch_response.processing_status
            logger.info("Anthropic batch job created with ID: %s", batch_id)
            logger.info("Status: %s", status)
            return (batch_id, status)
        except self.anthropic.APIError as e:
            from agent_actions.errors import AnthropicError

            raise AnthropicError(
                "Anthropic API error during batch submission",
                context={"operation": "batch_submission", "batch_name": batch_name},
                cause=e,
            ) from e
        except Exception as e:
            from agent_actions.errors import AnthropicError

            raise AnthropicError(
                "Failed to submit batch to Anthropic",
                context={"operation": "batch_submission", "batch_name": batch_name},
                cause=e,
            ) from e

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from Anthropic API."""
        batch_info = self.client.messages.batches.retrieve(batch_id)
        return str(batch_info.processing_status)

    def _normalize_status(self, raw_status: str) -> str:
        """Normalize Anthropic status to standard format."""
        # A batch being canceled has not ended yet; once ended, every request has a
        # result, a canceled one included.
        status_mapping = {
            "in_progress": "in_progress",
            "canceling": "in_progress",
            "ended": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "expired": "failed",
        }
        return status_mapping.get(raw_status, raw_status)

    def _get_result_file_name(self, batch_id: str) -> str:
        """Return the result file name for Anthropic batch results."""
        return f"{batch_id}_anthropic_raw_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Stream results from Anthropic API and return as JSONL bytes."""
        lines = []
        for entry in self.client.messages.batches.results(batch_id):
            if hasattr(entry, "model_dump"):
                lines.append(json.dumps(entry.model_dump()))
            elif hasattr(entry, "__dict__"):
                lines.append(json.dumps(entry.__dict__))
            else:
                lines.append(json.dumps(entry))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _validate_provider_specific_config(
        self, agent_config: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Validate Anthropic-specific configuration."""
        enable_prompt_caching = agent_config.get("enable_prompt_caching")
        if enable_prompt_caching is not None and not isinstance(enable_prompt_caching, bool):
            return (False, "enable_prompt_caching must be a boolean")
        return (True, None)
