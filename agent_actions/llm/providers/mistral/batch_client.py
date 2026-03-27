"""
Mistral Batch API client implementation.
"""

import logging
import os
from pathlib import Path
from typing import Any

from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchTask
from ..mixins import OpenAICompatibleResponseMixin

logger = logging.getLogger(__name__)


class MistralBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    Mistral Batch API implementation of the BaseBatchClient interface.

    Handles format transformations:
    - Input: BatchTask -> Mistral task format
    - Output: Mistral response -> BatchResult

    Features:
    - 50% cost discount for batch processing
    - Default 24h timeout (configurable to 7 days)
    - Supports json_object mode
    """

    # Status mapping from Mistral to standard format
    STATUS_MAPPING = {
        "QUEUED": "validating",
        "RUNNING": "in_progress",
        "SUCCESS": "completed",
        "FAILED": "failed",
        "TIMEOUT_EXCEEDED": "failed",
        "CANCELLED": "cancelled",
    }

    def __init__(self, api_key: str | None = None):
        """
        Initialize Mistral client with optional API key.

        Args:
            api_key: Mistral API key (falls back to MISTRAL_API_KEY env var)
        """
        try:
            from mistralai import Mistral

            self._mistral_module = Mistral
            resolved_key = api_key or os.getenv("MISTRAL_API_KEY")
            self.client = Mistral(api_key=resolved_key)
        except ImportError as e:
            from agent_actions.errors import DependencyError

            raise DependencyError(
                "MistralBatchProvider requires mistralai package",
                context={
                    "package": "mistralai",
                    "install_command": "uv pip install mistralai",
                    "vendor": "mistral",
                },
                cause=e,
            ) from e

    def _get_default_model(self) -> str:
        """Return Mistral's default model."""
        return "mistral-large-latest"

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Transform our BatchTask to Mistral's expected format.

        Mistral expects:
        {
            "custom_id": "request-1",
            "body": {
                "model": "mistral-large-latest",
                "max_tokens": 4096,
                "messages": [...],
                "response_format": {...}  # if json mode
            }
        }
        """
        model_name = batch_task.model_config.get("model_name", self._get_default_model())
        envelope = MessageBuilder.build_for_batch(
            "mistral", batch_task.prompt, batch_task.user_content, schema=schema
        )
        body: dict[str, Any] = {
            "model": model_name,
            "messages": envelope.to_dicts(),
        }

        # Add optional parameters
        self._add_optional_param(body, "temperature", batch_task.model_config.get("temperature"))
        self._add_optional_param(
            body, "max_tokens", batch_task.model_config.get("max_tokens"), default=4096
        )

        # Mistral uses json_object mode (no full schema enforcement in batch)
        if schema:
            body["response_format"] = {"type": "json_object"}

        return {
            "custom_id": batch_task.custom_id,
            "body": body,
        }

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSONL file for Mistral."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "mistral")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit batch to Mistral API."""
        from agent_actions.errors import VendorAPIError

        try:
            # Upload file
            with open(input_file, "rb") as f:
                file_content = f.read()
                batch_file = self.client.files.upload(
                    file={"file_name": input_file.name, "content": file_content},
                    purpose="batch",
                )

            batch_job = self.client.batch.jobs.create(
                input_files=[batch_file.id],
                model=self._configured_model or self._get_default_model(),
                endpoint="/v1/chat/completions",
                metadata={"name": batch_name},
            )

            logger.info("Mistral batch job created with ID: %s", batch_job.id)
            logger.info("Status: %s", batch_job.status)
            return (batch_job.id, batch_job.status)

        except Exception as e:
            raise VendorAPIError(
                vendor="mistral",
                endpoint="batch.jobs.create",
                context={"message": "Failed to submit Mistral batch job", "batch_name": batch_name},
                cause=e,
            ) from e

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from Mistral API."""
        batch_job = self.client.batch.jobs.get(job_id=batch_id)
        return str(batch_job.status)

    def _normalize_status(self, raw_status: str) -> str:
        """Normalize Mistral status to standard format."""
        return self.STATUS_MAPPING.get(raw_status, raw_status.lower())

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result filename for Mistral."""
        return f"{batch_id}_mistral_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Fetch raw results from Mistral API."""
        from agent_actions.errors import ValidationError, VendorAPIError

        batch_job = self.client.batch.jobs.get(job_id=batch_id)
        if batch_job.status != "SUCCESS":
            raise ValidationError(
                "Batch job is not completed",
                context={"batch_id": batch_id, "status": batch_job.status, "vendor": "mistral"},
            )

        output_file = batch_job.output_file
        if not output_file:
            raise VendorAPIError(
                vendor="mistral",
                endpoint="batch.jobs.get",
                context={
                    "message": "Batch completed but has no output file",
                    "batch_id": batch_id,
                    "error_file": getattr(batch_job, "error_file", None),
                },
            )

        result_content = self.client.files.download(file_id=output_file)
        if not result_content:
            raise VendorAPIError(
                vendor="mistral",
                endpoint="files.download",
                context={
                    "message": "Retrieved empty content from batch results",
                    "batch_id": batch_id,
                },
            )

        # Ensure we return bytes
        if isinstance(result_content, str):
            return result_content.encode("utf-8")
        return result_content  # type: ignore[return-value, no-any-return]

    # -- Mistral-specific overrides for response paths that differ from
    # the standard OpenAI-compatible format (body fallback at top level).

    def _resolve_response_data(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Resolve response data with Mistral's body-key fallback."""
        result = raw_response.get("response", raw_response.get("body", raw_response))
        return result  # type: ignore[return-value, no-any-return]

    def _extract_error_from_response(self, raw_response: dict[str, Any]) -> str | None:
        """Extract error from Mistral response, with body fallback."""
        if raw_response.get("error"):
            return str(raw_response["error"])
        response_data = self._resolve_response_data(raw_response)
        if "error" in response_data:
            return str(response_data["error"])
        status_code = response_data.get("status_code")
        if status_code and status_code != 200:
            return f"HTTP {status_code}"
        return None

    def _extract_content_from_response(self, raw_response: dict[str, Any]) -> Any:
        """Extract content from Mistral response, with body fallback."""
        response_data = self._resolve_response_data(raw_response)
        response_body = response_data.get("body", response_data)
        if "choices" in response_body and response_body["choices"]:
            choice = response_body["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                return choice["message"]["content"]
        return None

    def _extract_metadata_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from Mistral response, preserving id field."""
        response_data = self._resolve_response_data(raw_response)
        response_body = response_data.get("body", response_data)
        choices = response_body.get("choices", [{}])
        return {
            "model": response_body.get("model"),
            "finish_reason": choices[0].get("finish_reason") if choices else None,
            "id": response_body.get("id"),
        }

    def _extract_usage_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any] | None:
        """Extract usage from Mistral response, with body fallback."""
        response_data = self._resolve_response_data(raw_response)
        response_body = response_data.get("body", response_data)
        return response_body.get("usage")  # type: ignore[no-any-return]
