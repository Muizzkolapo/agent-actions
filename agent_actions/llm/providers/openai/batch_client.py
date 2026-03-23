"""
OpenAI Batch API client implementation.
"""

import logging
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchTask
from ..mixins import OpenAICompatibleResponseMixin

logger = logging.getLogger(__name__)


class OpenAIBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    OpenAI Batch API implementation of the BaseBatchClient interface.

    Handles format transformations:
    - Input: BatchTask → OpenAI task format
    - Output: OpenAI response → BatchResult
    """

    def __init__(self, api_key: str | None = None):
        """Initialize OpenAI client."""
        self.client = OpenAI(api_key=api_key)

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Transform our BatchTask to OpenAI's expected format.

        OpenAI expects:
        {
            "custom_id": "request-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4o-mini",
                "messages": [...],
                "response_format": {...}  # if schema provided
            }
        }
        """
        model_name = batch_task.model_config.get("model_name", "gpt-4o-mini")
        envelope = MessageBuilder.build_for_batch(
            "openai", batch_task.prompt, batch_task.user_content, schema=schema
        )
        body = {
            "model": model_name,
            "messages": envelope.to_dicts(),
        }
        default_temp_only_models = ["gpt-5-mini", "gpt-5-nano", "gpt-5"]
        if "temperature" in batch_task.model_config:
            temp_value = batch_task.model_config["temperature"]
            if model_name not in default_temp_only_models or temp_value == 1:
                if model_name not in default_temp_only_models:
                    body["temperature"] = temp_value
        if (
            "max_tokens" in batch_task.model_config
            and batch_task.model_config["max_tokens"] is not None
        ):
            body["max_tokens"] = batch_task.model_config["max_tokens"]
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _extract_metadata_from_response(self, raw_response: dict[str, Any]) -> dict[str, Any]:
        """Extract metadata from OpenAI response with OpenAI-specific fields."""
        metadata = super()._extract_metadata_from_response(raw_response)
        # Add OpenAI-specific fields if response body exists
        response_data = raw_response.get("response", {})
        response_body = response_data.get("body")
        if response_body:
            metadata["created"] = response_body.get("created")
            metadata["system_fingerprint"] = response_body.get("system_fingerprint")
        return metadata

    def _get_default_model(self) -> str:
        """Return OpenAI's default model."""
        return "gpt-4o-mini"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSONL file for OpenAI."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "openai")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit batch to OpenAI API."""
        with open(input_file, "rb") as f:
            batch_file = self.client.files.create(file=f, purpose="batch")
        batch_job = self.client.batches.create(
            input_file_id=batch_file.id, endpoint="/v1/chat/completions", completion_window="24h"
        )
        logger.info("OpenAI batch job created with ID: %s", batch_job.id)
        logger.info("Status: %s", batch_job.status)
        return (batch_job.id, batch_job.status)

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from OpenAI API."""
        batch_job = self.client.batches.retrieve(batch_id)
        return batch_job.status

    def _normalize_status(self, raw_status: str) -> str:
        """OpenAI statuses are already in standard format."""
        return raw_status

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result filename for OpenAI."""
        return f"{batch_id}_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Fetch raw results from OpenAI API."""
        batch_job = self.client.batches.retrieve(batch_id)
        if batch_job.status != "completed":
            from agent_actions.errors import ValidationError

            raise ValidationError(
                "Batch job is not completed",
                context={"batch_id": batch_id, "status": batch_job.status, "vendor": "openai"},
            )

        result_file_id = batch_job.output_file_id
        if not result_file_id:
            from agent_actions.errors import VendorAPIError

            error_file_id = getattr(batch_job, "error_file_id", None)
            raise VendorAPIError(
                vendor="openai",
                endpoint="batches.retrieve",
                context={
                    "message": "Batch completed but has no output file (all requests may have failed)",
                    "batch_id": batch_id,
                    "status": batch_job.status,
                    "error_file_id": error_file_id,
                    "request_counts": getattr(batch_job, "request_counts", None),
                    "suggestion": (
                        f"Check error file: {error_file_id}"
                        if error_file_id
                        else "Clear batch registry and resubmit"
                    ),
                },
            )

        result_content = self.client.files.content(result_file_id).content

        if not result_content or len(result_content) == 0:
            from agent_actions.errors import VendorAPIError

            raise VendorAPIError(
                vendor="openai",
                endpoint="files.content",
                context={
                    "message": "Retrieved empty content from batch results",
                    "batch_id": batch_id,
                    "result_file_id": result_file_id,
                },
            )

        return result_content
