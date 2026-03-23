"""
Anthropic Batch API client implementation.
"""

import json
import logging
from pathlib import Path
from typing import Any

from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchResult, BatchTask

logger = logging.getLogger(__name__)


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
        version: str | None = None,
        enable_prompt_caching: bool = False,
    ):
        """
        Initialize Anthropic client with optional configuration.

        Args:
            api_key: Anthropic API key
            version: API version header (e.g., "2023-06-01")
            enable_prompt_caching: Whether to enable prompt caching feature
        """
        self.version = version or "2023-06-01"
        self.enable_prompt_caching = enable_prompt_caching
        try:
            import anthropic

            self.anthropic = anthropic
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

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Transform our BatchTask to Anthropic's Message Batches API format.

        Anthropic Message Batches API expects:
        {
            "custom_id": "my-first-request",
            "params": {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": "Hello, world"}
                ]
            }
        }
        """
        envelope = MessageBuilder.build_for_batch(
            "anthropic", batch_task.prompt, batch_task.user_content, schema=schema
        )
        # Anthropic batch: system is a top-level param, user content is the message
        params = {
            "model": batch_task.model_config.get("model_name", "claude-3-5-sonnet-20241022"),
            "messages": envelope.to_dicts(role="user"),
        }
        system_dicts = envelope.to_dicts(role="system")
        if system_dicts and system_dicts[0]["content"]:
            params["system"] = system_dicts[0]["content"]
        self._add_optional_param(params, "temperature", batch_task.model_config.get("temperature"))
        self._add_optional_param(
            params, "max_tokens", batch_task.model_config.get("max_tokens"), default=4096
        )
        if schema:
            tools = self._create_json_tool_from_schema(schema)
            if tools:
                tool_name = tools[0]["name"]
                params["tools"] = tools
                params["tool_choice"] = {"type": "tool", "name": tool_name}
        if self.enable_prompt_caching:
            params["extra_headers"] = {"anthropic-beta": "prompt-caching-2024-07-31"}
        return {"custom_id": batch_task.custom_id, "params": params}

    def _extract_error_from_response(self, raw_response: Any) -> str | None:
        """Extract error from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        if result is None:
            return "Invalid response format from Anthropic"

        result_type = self._get_attribute_or_key(result, "type")
        if result_type == "failed":
            error_info = self._get_attribute_or_key(result, "error", {})
            return str(error_info) if error_info else "Batch processing failed"
        if result_type == "succeeded":
            return None
        else:
            return f"Unknown result type: {result_type}"

    def _extract_content_from_response(self, raw_response: Any) -> Any:
        """Extract content from Anthropic response."""
        result = self._get_attribute_or_key(raw_response, "result")
        message = self._get_attribute_or_key(result, "message", {})
        content_list = self._get_attribute_or_key(message, "content", [])
        return self._parse_content_list(content_list)

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
            "anthropic_version": self.version,
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
        return "claude-3-sonnet-20240229"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSON file for Anthropic."""
        file_name = f"{Path(batch_name).stem}_anthropic_batch_input.json"
        file_path = batch_dir / file_name
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump({"requests": tasks}, file, indent=2)
        logger.info("Anthropic batch input saved at: %s", file_path)
        return file_path

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit batch to Anthropic API."""
        try:
            # Read tasks from file to submit
            with open(input_file, encoding="utf-8") as f:
                data = json.load(f)
                tasks = data["requests"]

            batch_response = self.client.messages.batches.create(requests=tasks)
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
        return batch_info.processing_status

    def _normalize_status(self, raw_status: str) -> str:
        """Normalize Anthropic status to standard format."""
        status_mapping = {
            "in_progress": "in_progress",
            "ended": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "expired": "failed",
        }
        return status_mapping.get(raw_status, raw_status)

    def retrieve_results(
        self, batch_id: str, output_directory: str | None = None
    ) -> list[BatchResult]:
        """
        Retrieve and transform Anthropic batch results to our format.

        NOTE: Anthropic overrides the base template method because it streams
        result objects directly instead of returning JSONL bytes. This is a
        provider-specific optimization that doesn't fit the base template.

        Args:
            batch_id: Anthropic batch job ID
            output_directory: Optional directory for caching results

        Returns:
            List of BatchResult objects
        """
        try:
            status = self.check_status(batch_id)
            if status != "completed":
                return []
            results_stream = self.client.messages.batches.results(batch_id)
            batch_results = []
            raw_entries = []
            for entry in results_stream:
                batch_result = self.parse_provider_response(entry)
                batch_results.append(batch_result)
                if hasattr(entry, "model_dump"):
                    raw_entries.append(entry.model_dump())
                elif hasattr(entry, "__dict__"):
                    raw_entries.append(entry.__dict__)
                else:
                    raw_entries.append(entry)  # type: ignore[arg-type]
            if output_directory and raw_entries:
                batch_dir = self._get_batch_directory(output_directory)
                raw_results_file = batch_dir / f"{batch_id}_anthropic_raw_results.jsonl"
                with open(raw_results_file, "w", encoding="utf-8") as f:
                    for entry in raw_entries:  # type: ignore[assignment]
                        f.write(json.dumps(entry) + "\n")
            return batch_results
        except self.anthropic.APIError as e:
            from agent_actions.errors import AnthropicError

            raise AnthropicError(
                "Anthropic API error retrieving batch results",
                context={"operation": "retrieve_results", "batch_id": batch_id},
                cause=e,
            ) from e
        except Exception as e:
            from agent_actions.errors import AnthropicError

            raise AnthropicError(
                "Failed to retrieve Anthropic batch results",
                context={"operation": "retrieve_results", "batch_id": batch_id},
                cause=e,
            ) from e

    def _get_result_file_name(self, batch_id: str) -> str:
        """Not used by Anthropic (streams results instead of file-based)."""
        return f"{batch_id}_anthropic_raw_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Not used by Anthropic (overrides retrieve_results entirely)."""
        raise NotImplementedError("Anthropic uses custom streaming-based retrieve_results()")

    def _create_json_tool_from_schema(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Create an Anthropic tool definition from a JSON schema to force structured output.

        Args:
            schema: JSON schema dictionary or list of schema objects from BatchService

        Returns:
            List containing tool definition for structured JSON response
        """
        actual_schema = None
        tool_name = "json_response"
        schema_description = "Provide a structured JSON response"
        if isinstance(schema, list) and len(schema) > 0:  # type: ignore[unreachable]
            schema_obj = schema[0]  # type: ignore[unreachable]
            if isinstance(schema_obj, dict):
                actual_schema = schema_obj.get("input_schema", {})
                tool_name = (
                    schema_obj.get("name", "json_response").lower().replace("schema", "_response")
                )
                schema_description = schema_obj.get("description", schema_description)
        elif isinstance(schema, dict) and ("properties" in schema or "type" in schema):
            actual_schema = schema
            schema_description = schema.get("description", schema_description)
        else:
            return []
        if not actual_schema:
            return []
        properties = actual_schema.get("properties", {})
        required = actual_schema.get("required", [])
        if not properties:
            tool_schema = {
                "type": "object",
                "properties": {
                    "response": {"type": "string", "description": "The response content"}
                },
                "required": ["response"],
            }
        else:
            tool_schema = {"type": "object", "properties": properties, "required": required}
        tool_definition = {
            "name": tool_name,
            "description": f"Provide structured JSON output: {schema_description}",
            "input_schema": tool_schema,
        }
        return [tool_definition]

    def _validate_provider_specific_config(
        self, agent_config: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Validate Anthropic-specific configuration."""
        anthropic_version = agent_config.get("anthropic_version")
        if anthropic_version and not isinstance(anthropic_version, str):
            return (False, "anthropic_version must be a string")
        enable_prompt_caching = agent_config.get("enable_prompt_caching")
        if enable_prompt_caching is not None and not isinstance(enable_prompt_caching, bool):
            return (False, "enable_prompt_caching must be a boolean")
        return (True, None)
