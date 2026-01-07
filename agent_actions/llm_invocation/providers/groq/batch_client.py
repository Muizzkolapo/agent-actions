"""
Groq Batch API client implementation.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from ..batch_client_base import BaseBatchClient, BatchTask
from ..mixins import OpenAICompatibleResponseMixin


class GroqBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    Groq Batch API implementation of the BaseBatchClient interface.

    Handles format transformations:
    - Input: BatchTask -> Groq task format (OpenAI-compatible JSONL)
    - Output: Groq response -> BatchResult

    Features:
    - 50% cost discount for batch processing
    - Max 50,000 lines per file, 200MB max
    - Completion windows: 24h to 7 days
    """

    # Status mapping from Groq to standard format
    STATUS_MAPPING = {
        "validating": "validating",
        "in_progress": "in_progress",
        "completed": "completed",
        "failed": "failed",
        "expired": "failed",
        "cancelled": "cancelled",
    }

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Groq client with optional API key.

        Args:
            api_key: Groq API key (falls back to GROQ_API_KEY env var)
        """
        try:
            from groq import Groq

            self._groq_module = Groq
            resolved_key = api_key or os.getenv("GROQ_API_KEY")
            self.client = Groq(api_key=resolved_key)
        except ImportError as e:
            from agent_actions.errors import DependencyError

            raise DependencyError(
                "GroqBatchProvider requires groq package",
                context={
                    "package": "groq",
                    "install_command": "pip install groq",
                    "vendor": "groq",
                },
                cause=e,
            ) from e

    def _get_default_model(self) -> str:
        """Return Groq's default model."""
        return "llama-3.3-70b-versatile"

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Transform our BatchTask to Groq's expected format.

        Groq expects (OpenAI-compatible):
        {
            "custom_id": "request-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "llama-3.3-70b-versatile",
                "messages": [...],
                "response_format": {...}  # if schema provided
            }
        }
        """
        model_name = batch_task.model_config.get("model_name", self._get_default_model())
        body: Dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": batch_task.prompt},
                {"role": "user", "content": batch_task.user_content},
            ],
        }

        # Add optional parameters
        self._add_optional_param(body, "temperature", batch_task.model_config.get("temperature"))
        self._add_optional_param(body, "max_tokens", batch_task.model_config.get("max_tokens"))

        # Groq supports json_schema mode with strict: true
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {**schema, "strict": True},
            }

        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _prepare_batch_input_file(
        self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSONL file for Groq."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "groq")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> Tuple[str, str]:
        """Submit batch to Groq API."""
        from agent_actions.errors import VendorAPIError

        try:
            # Upload file
            with open(input_file, "rb") as f:
                batch_file = self.client.files.create(file=f, purpose="batch")

            # Create batch job (24h default, can be up to 7 days)
            batch_job = self.client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
            )

            print(f"Groq batch job created with ID: {batch_job.id}")
            print(f"Status: {batch_job.status}")
            return (batch_job.id, batch_job.status)

        except Exception as e:
            raise VendorAPIError(
                vendor="groq",
                endpoint="batches.create",
                context={"message": "Failed to submit Groq batch job", "batch_name": batch_name},
                cause=e,
            ) from e

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from Groq API."""
        batch_job = self.client.batches.retrieve(batch_id)
        return batch_job.status

    def _normalize_status(self, raw_status: str) -> str:
        """Normalize Groq status to standard format."""
        return self.STATUS_MAPPING.get(raw_status, raw_status)

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result filename for Groq."""
        return f"{batch_id}_groq_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Fetch raw results from Groq API."""
        from agent_actions.errors import (
            ValidationError,
            VendorAPIError,
        )

        batch_job = self.client.batches.retrieve(batch_id)
        if batch_job.status != "completed":
            raise ValidationError(
                "Batch job is not completed",
                context={"batch_id": batch_id, "status": batch_job.status, "vendor": "groq"},
            )

        result_file_id = batch_job.output_file_id
        if not result_file_id:
            error_file_id = getattr(batch_job, "error_file_id", None)
            raise VendorAPIError(
                vendor="groq",
                endpoint="batches.retrieve",
                context={
                    "message": "Batch completed but has no output file",
                    "batch_id": batch_id,
                    "error_file_id": error_file_id,
                },
            )

        result_content = self.client.files.content(result_file_id).content
        if not result_content:
            raise VendorAPIError(
                vendor="groq",
                endpoint="files.content",
                context={
                    "message": "Retrieved empty content from batch results",
                    "batch_id": batch_id,
                },
            )

        return result_content

    def _extract_metadata_from_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata from Groq response with Groq-specific fields."""
        # Get base metadata from mixin
        metadata = super()._extract_metadata_from_response(raw_response)
        # Add Groq-specific fields if response body exists
        response_data = raw_response.get("response", {})
        response_body = response_data.get("body")
        if response_body:
            metadata["created"] = response_body.get("created")
            metadata["system_fingerprint"] = response_body.get("system_fingerprint")
        return metadata
