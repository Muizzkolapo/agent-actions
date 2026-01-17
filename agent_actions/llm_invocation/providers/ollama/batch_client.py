"""
Ollama Local Batch Client - Simple local batch simulation.

Supports:
- Synchronous batch processing (simulates async interface)
- JSON mode with structured outputs
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from ollama import Client
from ..batch_client_base import BaseBatchClient, BatchTask, BatchResult
from ..mixins import OpenAICompatibleResponseMixin
from agent_actions.llm_invocation.providers.ollama.failure_injection import (
    should_fail_batch_record,
)

logger = logging.getLogger(__name__)


class OllamaBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """
    Ollama local batch client with in-process simulation.

    This client processes batches synchronously but maintains
    the same interface as true async clients (OpenAI, Anthropic).
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Ollama batch provider.

        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
        """
        self.base_url = base_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.client = Client(host=self.base_url)

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Format task as OpenAI-compatible JSONL (for consistency).
        """
        model_name = batch_task.model_config.get("model_name", "llama2")
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": batch_task.prompt},
                {"role": "user", "content": batch_task.user_content},
            ],
        }

        # Add optional parameters
        if "temperature" in batch_task.model_config:
            body["temperature"] = batch_task.model_config["temperature"]

        # Only add max_tokens if it's not None
        max_tokens = batch_task.model_config.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        # Add schema if provided
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}

        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def _get_default_model(self) -> str:
        """Return Ollama's default model."""
        return "llama2"

    def _get_default_temperature(self) -> float:
        """Return Ollama's default temperature. Ollama defaults to 1.0, not 0.1."""
        return 1.0

    def _prepare_batch_input_file(
        self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to JSONL file for Ollama."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "ollama")

    def _extract_ollama_schema(self, schema: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Extract the inner JSON schema for Ollama's format parameter.

        OpenAI format: {"name": "...", "strict": true, "schema": {...}}
        Ollama expects: {"type": "object", "properties": {...}, "required": [...]}
        """
        if not schema:
            return None

        # If schema has nested "schema" key (OpenAI format), extract it
        if "schema" in schema and isinstance(schema["schema"], dict):
            return schema["schema"]

        # If it's already a raw JSON schema, return as-is
        if "type" in schema or "properties" in schema:
            return schema

        return schema

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> Tuple[str, str]:
        """Process batch synchronously with Ollama (no actual API submission)."""
        # Generate batch ID
        batch_id = f"batch_{uuid.uuid4().hex}"

        # Read tasks from input file
        tasks = []
        with open(input_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        # Process all tasks immediately
        results = []
        completed = 0
        failed = 0

        for idx, task in enumerate(tasks):
            custom_id = task["custom_id"]
            logger.info("Processing request %d/%d: %s", idx + 1, len(tasks), custom_id)

            try:
                # Extract request data
                body = task["body"]
                messages = body["messages"]
                model = body.get("model", "llama2")

                # Build options dict
                options = {
                    "temperature": (
                        body.get("temperature") if body.get("temperature") is not None else 1.0
                    )
                }
                max_tokens = body.get("max_tokens")
                if max_tokens is not None:
                    options["num_predict"] = max_tokens

                # Handle JSON mode with structured outputs
                format_param = None
                response_format = body.get("response_format")
                if response_format and isinstance(response_format, dict):
                    if response_format.get("type") == "json_schema":
                        json_schema = response_format.get("json_schema", {})
                        # Extract actual schema for Ollama
                        format_param = self._extract_ollama_schema(json_schema)
                        if not format_param:
                            format_param = "json"

                # Call Ollama
                ollama_response = self.client.chat(
                    model=model, messages=messages, options=options, format=format_param
                )

                # Failure injection AFTER successful call - simulates "result lost/missing"
                # We simply don't add this result, making it a "missing" record for retry
                if should_fail_batch_record(custom_id, idx):
                    logger.debug(f"[INJECTION] Simulating missing result for {custom_id}")
                    # Don't add to results - this makes it truly "missing"
                    failed += 1
                    continue

                # Transform to OpenAI format
                openai_response = self._transform_ollama_response(ollama_response, custom_id, model)

                results.append(openai_response)
                completed += 1

            except Exception as e:
                logger.error("Error processing %s: %s", custom_id, e)
                error_response = {
                    "custom_id": custom_id,
                    "response": None,
                    "error": {"message": str(e), "type": "ollama_error", "code": "inference_error"},
                }
                results.append(error_response)
                failed += 1

        # Write output JSONL file
        batch_dir = input_file.parent
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        with open(output_file_path, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result) + "\n")

        logger.info("Ollama batch output file: %s", output_file_path)
        logger.info("Batch completed: %d succeeded, %d failed", completed, failed)

        # Return 'submitted' to mimic async providers
        return (batch_id, "submitted")

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status. Ollama processes synchronously, so always completed."""
        return "completed"

    def _normalize_status(self, raw_status: str) -> str:
        """Ollama statuses are already in standard format."""
        return raw_status

    def retrieve_results(
        self, batch_id: str, output_directory: Optional[str] = None
    ) -> List[BatchResult]:
        """
        Retrieve results from output JSONL file.

        NOTE: Ollama overrides the base template method because it needs to use
        the same output_directory where results were written during submit_batch.
        """
        batch_dir = self._get_batch_directory(output_directory)
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"
        return self._read_jsonl_file(output_file_path)

    def _get_result_file_name(self, batch_id: str) -> str:
        """Not used by Ollama (overrides retrieve_results)."""
        return f"{batch_id}_results.jsonl"

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Not used by Ollama (overrides retrieve_results)."""
        raise NotImplementedError("Ollama uses custom file-based retrieve_results()")

    def _transform_ollama_response(self, ollama_response: dict, custom_id: str, model: str) -> dict:
        """
        Transform Ollama response to OpenAI batch output format.

        Ollama returns:
        {
            "model": "llama2",
            "message": {"role": "assistant", "content": "..."},
            "done": true,
            "prompt_eval_count": 10,
            "eval_count": 5
        }

        Transform to:
        {
            "custom_id": "request-1",
            "response": {
                "status_code": 200,
                "body": {
                    "id": "chatcmpl-xyz",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "llama2",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": "..."},
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15
                    }
                }
            },
            "error": null
        }
        """
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
                            "message": {
                                "role": ollama_response["message"]["role"],
                                "content": ollama_response["message"]["content"],
                            },
                            "finish_reason": "stop" if ollama_response.get("done") else "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": ollama_response.get("prompt_eval_count", 0),
                        "completion_tokens": ollama_response.get("eval_count", 0),
                        "total_tokens": (
                            ollama_response.get("prompt_eval_count", 0)
                            + ollama_response.get("eval_count", 0)
                        ),
                    },
                    "system_fingerprint": None,
                },
            },
            "error": None,
        }
