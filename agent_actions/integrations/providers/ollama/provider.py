"""
Ollama Local Batch Provider - Simple local batch simulation.

This provider simulates batch processing by:
1. Writing input JSONL files
2. Processing all requests immediately using Ollama
3. Writing output JSONL files

No external API server needed - everything runs in-process.
Registry tracking is handled by BatchService, not this provider.
"""

import json
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

from ollama import Client
from ..base import BatchProvider, BatchTask, BatchResult


class OllamaLocalBatchProvider(BatchProvider):
    """
    Ollama local batch provider with in-process simulation.

    This provider processes batches synchronously but maintains
    the same interface as true async providers (OpenAI, Anthropic).
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Ollama batch provider.

        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
        """
        import os
        self.base_url = base_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.client = Client(host=self.base_url)

    def format_task_for_provider(self,
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Format task as OpenAI-compatible JSONL (for consistency).
        """
        model_name = batch_task.model_config.get("model_name", "llama2")
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": batch_task.prompt},
                {"role": "user", "content": batch_task.user_content}
            ]
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
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": schema
            }

        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body
        }

    def parse_provider_response(self, raw_response: Dict[str, Any]) -> BatchResult:
        """
        Parse JSONL output format to BatchResult.

        Expected format:
        {
            "custom_id": "request-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": "..."}}],
                    "usage": {...}
                }
            },
            "error": null
        }
        """
        custom_id = raw_response.get("custom_id", "unknown")

        # Check for errors
        if raw_response.get("error"):
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=str(raw_response["error"]),
                metadata={"raw_error": raw_response["error"]}
            )

        response_data = raw_response.get("response", {})
        response_body = response_data.get("body", {})

        # Extract content
        content = None
        if "choices" in response_body and response_body["choices"]:
            choice = response_body["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                content_str = choice["message"]["content"]

                # Try to parse as JSON
                try:
                    content = json.loads(content_str)
                except json.JSONDecodeError:
                    content = content_str

        # Build metadata
        metadata = {
            "model": response_body.get("model"),
            "usage": response_body.get("usage"),
            "finish_reason": response_body.get("choices", [{}])[0].get("finish_reason"),
            "status_code": response_data.get("status_code")
        }

        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=response_data.get("status_code") == 200,
            error=None if response_data.get("status_code") == 200 else f"HTTP {response_data.get('status_code')}",
            metadata=metadata,
            usage=response_body.get("usage")
        )

    def prepare_tasks(self,
                     data: List[Dict[str, Any]],
                     agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data to JSONL task format.
        """
        tasks = []

        # Only use schema if json_mode is enabled
        # When json_mode is False, we should NOT add response_format/schema
        json_mode = agent_config.get("json_mode", True)  # Default to True for backwards compatibility
        schema = agent_config.get("compiled_schema") if json_mode else None

        for row in data:
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=row.get("prompt", agent_config.get("prompt", "")),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", "llama2"),
                    "temperature": agent_config.get("temperature", 1.0),
                    "max_tokens": agent_config.get("max_tokens")
                },
                metadata=row
            )

            task = self.format_task_for_provider(batch_task, schema)
            tasks.append(task)

        return tasks

    def submit_batch(self,
                    tasks: List[Dict[str, Any]],
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """
        Submit batch and process immediately.

        This method:
        1. Writes input JSONL file
        2. Processes all tasks using Ollama
        3. Writes output JSONL file
        4. Returns batch_id

        Note: Registry is managed by BatchService, not this provider.
        """
        # Use base class helper for directory setup
        batch_dir = self._get_batch_directory(output_directory)

        # Generate batch ID
        batch_id = f"batch_{uuid.uuid4().hex}"

        # Use base class helper to write input JSONL
        input_file_path = self._write_jsonl_file(tasks, batch_dir, batch_name, "ollama")

        # Process all tasks immediately
        results = []
        completed = 0
        failed = 0

        for idx, task in enumerate(tasks, 1):
            print(f"Processing request {idx}/{len(tasks)}: {task['custom_id']}")

            try:
                # Extract request data
                body = task["body"]
                messages = body["messages"]
                model = body.get("model", "llama2")

                # Call Ollama
                # Build options dict, handling None values
                options = {
                    "temperature": body.get("temperature") if body.get("temperature") is not None else 1.0
                }
                # Only add num_predict if max_tokens is specified
                max_tokens = body.get("max_tokens")
                if max_tokens is not None:
                    options["num_predict"] = max_tokens

                # Check if response_format is specified (for JSON mode)
                # Ollama uses 'format' parameter, not 'response_format'
                format_param = None
                response_format = body.get("response_format")
                if response_format and isinstance(response_format, dict):
                    if response_format.get("type") == "json_schema":
                        # Ollama expects format="json" for JSON mode
                        format_param = "json"

                ollama_response = self.client.chat(
                    model=model,
                    messages=messages,
                    options=options,
                    format=format_param
                )

                # Transform to OpenAI format
                openai_response = self._transform_ollama_response(
                    ollama_response,
                    task["custom_id"],
                    model
                )

                results.append(openai_response)
                completed += 1

            except Exception as e:
                print(f"Error processing {task['custom_id']}: {e}")

                # Create error response
                error_response = {
                    "custom_id": task["custom_id"],
                    "response": None,
                    "error": {
                        "message": str(e),
                        "type": "ollama_error",
                        "code": "inference_error"
                    }
                }
                results.append(error_response)
                failed += 1

        # Write output JSONL file
        output_file_name = f"{batch_id}_results.jsonl"
        output_file_path = batch_dir / output_file_name

        with open(output_file_path, 'w') as f:
            for result in results:
                f.write(json.dumps(result) + '\n')

        print(f"Ollama batch output file: {output_file_path}")
        print(f"Batch completed: {completed} succeeded, {failed} failed")

        # Note: Registry is managed by BatchService, not this provider
        return batch_id

    def check_status(self, batch_id: str) -> str:
        """
        Check batch status.

        Since we process synchronously, always returns "completed".
        """
        # In a real implementation, you could read from registry
        # For simplicity, we assume if batch_id exists, it's completed
        return "completed"

    def retrieve_results(self,
                        batch_id: str,
                        output_directory: Optional[str] = None) -> List[BatchResult]:
        """
        Retrieve results from output JSONL file.
        """
        # Use base class helper for directory
        batch_dir = self._get_batch_directory(output_directory)
        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        # Use base class helper to read and parse JSONL
        return self._read_jsonl_file(output_file_path)

    def _transform_ollama_response(self,
                                   ollama_response: dict,
                                   custom_id: str,
                                   model: str) -> dict:
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
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": ollama_response["message"]["role"],
                            "content": ollama_response["message"]["content"]
                        },
                        "finish_reason": "stop" if ollama_response.get("done") else "length"
                    }],
                    "usage": {
                        "prompt_tokens": ollama_response.get("prompt_eval_count", 0),
                        "completion_tokens": ollama_response.get("eval_count", 0),
                        "total_tokens": (
                            ollama_response.get("prompt_eval_count", 0) +
                            ollama_response.get("eval_count", 0)
                        )
                    },
                    "system_fingerprint": None
                }
            },
            "error": None
        }
