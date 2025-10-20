"""
Ollama Local Batch Provider - Simple local batch simulation.

This provider simulates batch processing by:
1. Writing input JSONL files
2. Processing all requests immediately using Ollama
3. Writing output JSONL files
4. Tracking batches in a local JSON registry

No external API server needed - everything runs in-process.
"""

import json
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from ollama import Client
from ..base import BatchProvider, BatchTask, BatchResult
from agent_actions.core.utils.path_utils import ensure_directory_exists


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
        4. Updates batch registry
        5. Returns batch_id
        """
        # Setup directories
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"

        ensure_directory_exists(batch_dir)

        # Generate batch ID
        batch_id = f"batch_{uuid.uuid4().hex}"

        # Write input JSONL file
        input_file_name = f"{Path(batch_name).stem}_ollama_batch_input.jsonl"
        input_file_path = batch_dir / input_file_name

        with open(input_file_path, 'w') as f:
            for task in tasks:
                f.write(json.dumps(task) + '\n')

        print(f"Ollama batch input file: {input_file_path}")

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

        # Update batch registry
        self._update_registry(
            batch_dir,
            batch_name,
            batch_id,
            len(tasks),
            completed,
            failed
        )

        print(f"Batch completed: {completed} succeeded, {failed} failed")
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
        # Find output file
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"

        output_file_path = batch_dir / f"{batch_id}_results.jsonl"

        if not output_file_path.exists():
            from agent_actions.core.exceptions import VendorAPIError
            raise VendorAPIError(
                "Batch output file not found",
                context={
                    'batch_id': batch_id,
                    'expected_path': str(output_file_path),
                    'vendor': 'ollama'
                }
            )

        # Parse results
        batch_results = []
        with open(output_file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                        batch_results.append(BatchResult(
                            custom_id=f"error_line_{line_num}",
                            content=None,
                            success=False,
                            error=f"JSON parsing error: {e}",
                            metadata={"line_number": line_num}
                        ))

        return batch_results

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

    def _update_registry(self,
                        batch_dir: Path,
                        batch_name: str,
                        batch_id: str,
                        total: int,
                        completed: int,
                        failed: int):
        """
        Update local batch registry file.

        Registry format matches existing agent-actions pattern:
        {
            "batch_name.json": {
                "batch_id": "batch_abc123",
                "status": "completed",
                "timestamp": "2025-10-20T...",
                "provider": "ollama",
                "record_count": 100
            }
        }
        """
        registry_path = batch_dir / ".batch_registry.json"

        # Read existing registry
        if registry_path.exists():
            with open(registry_path, 'r') as f:
                registry = json.load(f)
        else:
            registry = {}

        # Update registry
        registry[batch_name] = {
            "batch_id": batch_id,
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "provider": "ollama",
            "parent_batch_id": None,
            "retry_attempt": 0,
            "has_retry_batch": False,
            "record_count": total,
            "completed_count": completed,
            "failed_count": failed
        }

        # Write registry
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)
