"""
Gemini Batch API client implementation.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchTask


class GeminiBatchClient(BaseBatchClient):
    """
    Gemini Batch API implementation of the BaseBatchClient interface.

    Handles format transformations:
    - Input: BatchTask → Gemini task format
    - Output: Gemini response → BatchResult
    """

    def __init__(self, api_key: str | None = None):
        """Initialize Gemini client."""
        if not GEMINI_AVAILABLE:
            from agent_actions.errors import DependencyError

            raise DependencyError(
                "GeminiBatchProvider requires google-genai package",
                context={
                    "package": "google-genai",
                    "install_command": "uv pip install google-genai",
                    "vendor": "gemini",
                },
            )
        self.client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Transform our BatchTask to Gemini's expected format.

        Gemini expects:
        {
            "key": "request-1",
            "request": {
                "contents": [{
                    "parts": [{
                        "text": "system prompt + user content"
                    }]
                }],
                "generation_config": {
                    "temperature": 0.1,
                    "max_tokens": 1000
                }
            }
        }
        """
        envelope = MessageBuilder.build_for_batch(
            "gemini", batch_task.prompt, batch_task.user_content, schema=schema
        )
        combined_text = envelope.messages[0].content
        generation_config = {}
        if "temperature" in batch_task.model_config:
            generation_config["temperature"] = batch_task.model_config["temperature"]
        if "max_tokens" in batch_task.model_config:
            generation_config["max_tokens"] = batch_task.model_config["max_tokens"]
        request: dict[str, Any] = {"contents": [{"parts": [{"text": combined_text}]}]}
        if generation_config:
            request["generation_config"] = generation_config
        if schema:
            request["response_schema"] = schema
            request["response_mime_type"] = "application/json"
        return {"key": batch_task.custom_id, "request": request}

    def _extract_custom_id(self, raw_response: dict[str, Any]) -> str:
        """Extract custom_id from Gemini response (uses 'key' instead)."""
        return raw_response.get("key", "unknown")  # type: ignore[no-any-return]

    def _extract_error_from_response(self, raw_response: dict[str, Any]) -> str | None:
        """Extract error from Gemini response."""
        if "error" in raw_response:
            return str(raw_response["error"])
        # Check if content is missing (Gemini-specific error condition)
        response_data = raw_response.get("response", {})
        candidates = response_data.get("candidates", [])
        if not candidates:
            return "No candidates in response"
        candidate = candidates[0]
        candidate_content = candidate.get("content", {})
        parts = candidate_content.get("parts", [])
        if not parts or not parts[0].get("text"):
            return "No content in response"
        return None

    def _extract_content_from_response(self, raw_response: dict[str, Any]) -> Any:
        """Extract content from Gemini response."""
        response_data = raw_response.get("response", {})
        candidates = response_data.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            candidate_content = candidate.get("content", {})
            parts = candidate_content.get("parts", [])
            if parts:
                return parts[0].get("text", "")
        return None

    def _extract_metadata_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from Gemini response."""
        response_data = raw_response.get("response", {})
        candidates = response_data.get("candidates", [])
        return {
            "model_version": response_data.get("modelVersion"),
            "response_id": response_data.get("responseId"),
            "finish_reason": candidates[0].get("finishReason") if candidates else None,
        }

    def _extract_usage_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any] | None:
        """Extract usage from Gemini response."""
        response_data = raw_response.get("response", {})
        usage_metadata = response_data.get("usageMetadata", {})
        return {
            "total_tokens": usage_metadata.get("totalTokenCount"),
            "prompt_tokens": usage_metadata.get("promptTokenCount"),
            "completion_tokens": usage_metadata.get("candidatesTokenCount"),
        }

    def _get_default_model(self) -> str:
        """Return Gemini's default model."""
        return "gemini-2.5-flash"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSONL file for Gemini."""
        file_name = f"{Path(batch_name).stem}_batch_input.json"
        file_path = batch_dir / file_name
        with open(file_path, "w", encoding="utf-8") as file:
            for task in tasks:
                file.write(json.dumps(task) + "\n")
        logger.info("Gemini batch file created at: %s", file_path)
        return file_path

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit batch to Gemini API."""
        try:
            logger.info("Uploading file: %s", input_file)
            uploaded_file = self.client.files.upload(
                file=str(input_file),
                config=types.UploadFileConfig(display_name=f"{batch_name}-batch-input"),
            )
            logger.info("Uploaded file: %s", uploaded_file.name)
            model_name = self._configured_model or self._get_default_model()
            batch_job = self.client.batches.create(
                model=model_name,
                src=uploaded_file.name,  # type: ignore[arg-type]
                config={"display_name": batch_name},  # type: ignore[arg-type]
            )
            logger.info("Gemini batch job created with ID: %s", batch_job.name)
            status = (
                batch_job.state.name if hasattr(batch_job.state, "name") else str(batch_job.state)  # type: ignore[union-attr]
            )
            return (batch_job.name, status)  # type: ignore[return-value]
        except Exception as e:
            from agent_actions.errors import VendorAPIError

            raise VendorAPIError(
                vendor="gemini",
                endpoint="batches.create",
                context={"message": "Failed to submit Gemini batch job", "batch_name": batch_name},
                cause=e,
            ) from e

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from Gemini API."""
        batch_job = self.client.batches.get(name=batch_id)
        return batch_job.state.name  # type: ignore[union-attr]

    def _normalize_status(self, raw_status: str) -> str:
        """Normalize Gemini status to standard format."""
        status_mapping = {
            "JOB_STATE_PENDING": "in_progress",
            "JOB_STATE_RUNNING": "in_progress",
            "JOB_STATE_SUCCEEDED": "completed",
            "JOB_STATE_FAILED": "failed",
            "JOB_STATE_CANCELLED": "cancelled",
        }
        return status_mapping.get(raw_status, raw_status.lower())

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result filename for Gemini."""
        return f"{batch_id.replace('/', '_')}_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Fetch raw results from Gemini API."""
        batch_job = self.client.batches.get(name=batch_id)
        if batch_job.state.name != "JOB_STATE_SUCCEEDED":  # type: ignore[union-attr]
            from agent_actions.errors import ValidationError

            raise ValidationError(
                "Batch job is not completed",
                context={"batch_id": batch_id, "status": batch_job.state.name, "vendor": "gemini"},  # type: ignore[union-attr]
            )

        result_file_name = batch_job.dest.file_name  # type: ignore[union-attr]
        if not result_file_name:
            from agent_actions.errors import ValidationError

            raise ValidationError(
                "Batch job has no output file", context={"batch_id": batch_id, "vendor": "gemini"}
            )

        logger.info("Results are in file: %s", result_file_name)
        logger.debug("Downloading result file content...")
        file_content_bytes = self.client.files.download(file=result_file_name)

        if not file_content_bytes or len(file_content_bytes) == 0:
            from agent_actions.errors import VendorAPIError

            raise VendorAPIError(
                vendor="gemini",
                endpoint="files.download",
                context={
                    "message": "Retrieved empty content from batch results",
                    "batch_id": batch_id,
                    "result_file_name": result_file_name,
                },
            )

        return file_content_bytes
