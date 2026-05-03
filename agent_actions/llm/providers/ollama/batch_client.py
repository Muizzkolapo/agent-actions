"""
Ollama Batch Client — synchronous batch simulation for local and cloud.

Both vendors use the same fake synchronous loop (no real batch API exists
for either). The ``cloud`` flag controls client construction (Bearer auth)
and whether the ``format`` param is passed to ``client.chat()``.

When Ollama ships a real cloud batch API, add a
``_submit_to_cloud_batch_api`` branch inside ``_submit_to_provider_api``.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from ollama import Client

from agent_actions.config.defaults import OllamaCloudDefaults, OllamaDefaults
from agent_actions.errors import ConfigurationError, VendorAPIError
from agent_actions.llm.providers.ollama.failure_injection import (
    should_fail_batch_record,
)
from agent_actions.prompt.message_builder import MessageBuilder

from ..batch_base import BaseBatchClient, BatchResult, BatchTask
from ..mixins import OpenAICompatibleResponseMixin

logger = logging.getLogger(__name__)


class OllamaBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    Ollama batch client with in-process simulation.

    Parameterized by ``vendor_slug`` and ``cloud`` to serve both
    ``ollama_local`` and ``ollama_cloud`` from a single class.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        vendor_slug: str = "ollama_local",
        cloud: bool = False,
    ):
        self.vendor_slug = vendor_slug
        self.cloud = cloud

        if cloud:
            self.base_url = base_url or os.getenv("OLLAMA_CLOUD_HOST", OllamaCloudDefaults.BASE_URL)
            if not api_key:
                raise ConfigurationError(
                    "ollama_cloud batch requires an API key",
                    context={
                        "vendor": "ollama_cloud",
                        "hint": (
                            "Set api_key in your action config or export OLLAMA_API_KEY. "
                            "Create a key at https://ollama.com/settings/keys"
                        ),
                    },
                )
            self.client = Client(
                host=self.base_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        else:
            self.base_url = base_url or os.getenv("OLLAMA_HOST", OllamaDefaults.BASE_URL)
            self.client = Client(host=self.base_url)

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Format task as OpenAI-compatible JSONL (for consistency)."""
        model_name = batch_task.model_config.get("model_name", "llama2")
        envelope = MessageBuilder.build_for_batch(
            self.vendor_slug, batch_task.prompt, batch_task.user_content, schema=schema
        )
        body: dict[str, Any] = {
            "model": model_name,
            "messages": envelope.to_dicts(),
        }

        if "temperature" in batch_task.model_config:
            body["temperature"] = batch_task.model_config["temperature"]

        max_tokens = batch_task.model_config.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}

        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _get_default_model(self) -> str:
        return "llama2"

    def _get_default_temperature(self) -> float:
        return 1.0

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        return self._write_jsonl_file(tasks, batch_dir, batch_name, self.vendor_slug)

    def _extract_ollama_schema(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """Extract inner JSON schema for Ollama's format parameter."""
        if not schema:
            return None
        if "schema" in schema and isinstance(schema["schema"], dict):
            return schema["schema"]
        if "type" in schema or "properties" in schema:
            return schema
        return schema

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Process batch synchronously (no actual API submission)."""
        batch_id = f"batch_{uuid.uuid4().hex}"

        tasks = []
        with open(input_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        results = []
        completed = 0
        failed = 0

        for idx, task in enumerate(tasks):
            custom_id = task["custom_id"]
            logger.info("Processing request %d/%d: %s", idx + 1, len(tasks), custom_id)

            try:
                body = task["body"]
                messages = body["messages"]
                model = body.get("model", "llama2")

                options: dict[str, Any] = {
                    "temperature": (
                        body.get("temperature") if body.get("temperature") is not None else 1.0
                    )
                }
                max_tokens = body.get("max_tokens")
                if max_tokens is not None:
                    options["num_predict"] = max_tokens

                # Handle JSON mode with structured outputs.
                # Cloud: format param not supported (ollama/ollama#12362).
                format_param: str | dict[str, Any] | None = None
                if not self.cloud:
                    response_format = body.get("response_format")
                    if response_format and isinstance(response_format, dict):
                        if response_format.get("type") == "json_schema":
                            json_schema = response_format.get("json_schema", {})
                            format_param = self._extract_ollama_schema(json_schema)
                            if not format_param:
                                format_param = "json"

                ollama_response = self.client.chat(
                    model=model,
                    messages=messages,
                    options=options,
                    format=format_param,  # type: ignore[arg-type]
                )

                if should_fail_batch_record(custom_id, idx):
                    logger.debug("[INJECTION] Simulating missing result for %s", custom_id)
                    failed += 1
                    continue

                openai_response = self._transform_ollama_response(
                    ollama_response,
                    custom_id,
                    model,  # type: ignore[arg-type]
                )
                results.append(openai_response)
                completed += 1

            except Exception as e:
                logger.error("Error processing %s: %s", custom_id, e)
                error_response = {
                    "custom_id": custom_id,
                    "response": None,
                    "error": {
                        "message": str(e),
                        "type": "ollama_error",
                        "code": "inference_error",
                    },
                }
                results.append(error_response)
                failed += 1

        batch_dir = input_file.parent
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        with open(output_file_path, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        logger.info("%s batch output file: %s", self.vendor_slug, output_file_path)
        if failed > 0:
            logger.warning(
                "Batch completed with failures: %d succeeded, %d failed", completed, failed
            )
        else:
            logger.info("Batch completed successfully: %d records", completed)

        return (batch_id, "submitted")

    def _fetch_status(self, batch_id: str) -> str:
        return "completed"

    def _normalize_status(self, raw_status: str) -> str:
        return raw_status

    def retrieve_results(
        self, batch_id: str, output_directory: str | None = None
    ) -> list[BatchResult]:
        batch_dir = self._get_batch_directory(output_directory)
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"
        return self._read_jsonl_file(output_file_path)

    def _get_result_file_name(self, batch_id: str) -> str:
        return f"{batch_id}_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        raise NotImplementedError("Ollama uses custom file-based retrieve_results()")

    def _transform_ollama_response(
        self, ollama_response: dict | object, custom_id: str, model: str
    ) -> dict:
        """Transform Ollama response to OpenAI batch output format."""
        if isinstance(ollama_response, dict):
            _msg = ollama_response.get("message", {})
            role = _msg.get("role") if isinstance(_msg, dict) else getattr(_msg, "role", None)
            content = (
                _msg.get("content") if isinstance(_msg, dict) else getattr(_msg, "content", None)
            )
        else:
            _msg = getattr(ollama_response, "message", None)
            role = getattr(_msg, "role", None) if _msg else None
            content = getattr(_msg, "content", None) if _msg else None

        if not role or content is None:
            raise VendorAPIError(
                f"Ollama response missing or malformed 'message' field for {custom_id!r}",
                context={"vendor": self.vendor_slug, "custom_id": custom_id},
            )

        return {
            "custom_id": custom_id,
            "response": {
                "status_code": 200,
                "request_id": f"req-{uuid.uuid4().hex[:12]}",
                "body": {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": role, "content": content},
                            "finish_reason": "stop"
                            if (
                                ollama_response.get("done")
                                if isinstance(ollama_response, dict)
                                else getattr(ollama_response, "done", False)
                            )
                            else "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": (
                            ollama_response.get("prompt_eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "prompt_eval_count", None) or 0
                        ),
                        "completion_tokens": (
                            ollama_response.get("eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "eval_count", None) or 0
                        ),
                        "total_tokens": (
                            ollama_response.get("prompt_eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "prompt_eval_count", None) or 0
                        )
                        + (
                            ollama_response.get("eval_count", 0)
                            if isinstance(ollama_response, dict)
                            else getattr(ollama_response, "eval_count", None) or 0
                        ),
                    },
                    "system_fingerprint": None,
                },
            },
            "error": None,
        }
