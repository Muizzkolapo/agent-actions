"""
OpenAI Batch API provider implementation.

This module implements the BatchProvider interface for OpenAI's Batch API,
handling the transformation between our standardized format and OpenAI's
specific requirements.
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from openai import OpenAI

from .base import BatchProvider, BatchTask, BatchResult
from ..utils.path_utils import ensure_directory_exists
from ..models.schema_change import compile_unified_schema


class OpenAIBatchProvider(BatchProvider):
    """
    OpenAI Batch API implementation of the BatchProvider interface.
    
    Handles format transformations:
    - Input: BatchTask → OpenAI task format
    - Output: OpenAI response → BatchResult
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI client."""
        self.client = OpenAI(api_key=api_key)
        
    def format_task_for_provider(self, 
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        body = {
            "model": batch_task.model_config.get("model_name", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": batch_task.prompt},
                {"role": "user", "content": batch_task.user_content}
            ]
        }
        
        # Add optional parameters from model_config
        if "temperature" in batch_task.model_config:
            body["temperature"] = batch_task.model_config["temperature"]
        if "max_tokens" in batch_task.model_config:
            body["max_tokens"] = batch_task.model_config["max_tokens"]
            
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
        Transform OpenAI's response format to our standardized BatchResult.
        
        OpenAI returns:
        {
            "custom_id": "request-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{
                        "message": {"content": "..."},
                        "finish_reason": "stop"
                    }],
                    "usage": {...},
                    "model": "gpt-4o-mini"
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
        
        # Extract content from choices
        content = None
        if "choices" in response_body and response_body["choices"]:
            choice = response_body["choices"][0]
            if "message" in choice and "content" in choice["message"]:
                content_str = choice["message"]["content"]
                
                # Try to parse as JSON if it looks like JSON
                try:
                    content = json.loads(content_str)
                except json.JSONDecodeError:
                    content = content_str
        
        # Build metadata
        metadata = {
            "model": response_body.get("model"),
            "usage": response_body.get("usage"),
            "finish_reason": response_body.get("choices", [{}])[0].get("finish_reason"),
            "created": response_body.get("created"),
            "system_fingerprint": response_body.get("system_fingerprint"),
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
        Convert agent-actions data to OpenAI batch format.
        
        This method orchestrates the transformation of multiple data items
        into OpenAI-formatted tasks.
        """
        tasks = []
        
        # Get schema if configured
        # The batch service already compiles and passes the schema as "compiled_schema"
        schema = agent_config.get("compiled_schema")
        
        for row in data:
            # Create BatchTask from row data
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=agent_config.get("prompt", ""),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", "gpt-4o-mini"),
                    "temperature": agent_config.get("temperature", 0.1),
                    "max_tokens": agent_config.get("max_tokens")
                },
                metadata=row
            )
            
            # Transform to OpenAI format
            openai_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(openai_task)
        
        return tasks
    
    def submit_batch(self, 
                    tasks: List[Dict[str, Any]], 
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """Submit batch job to OpenAI."""
        # Create batch directory
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"
        
        ensure_directory_exists(batch_dir)
        
        # Write tasks to JSONL file
        file_name = f"{Path(batch_name).stem}_batch_input.jsonl"
        file_path = batch_dir / file_name
        
        with open(file_path, 'w') as file:
            for task in tasks:
                file.write(json.dumps(task) + '\n')
        
        print(f"OpenAI batch file created at: {file_path}")
        
        # Upload file to OpenAI
        batch_file = self.client.files.create(
            file=open(file_path, "rb"),
            purpose="batch"
        )
        
        # Create batch job
        batch_job = self.client.batches.create(
            input_file_id=batch_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        
        print(f"OpenAI batch job created with ID: {batch_job.id}")
        return batch_job.id
    
    def check_status(self, batch_id: str) -> str:
        """Check OpenAI batch job status."""
        try:
            batch_job = self.client.batches.retrieve(batch_id)
            return batch_job.status
        except Exception as e:
            raise RuntimeError(f"Error checking OpenAI batch status: {e}")
    
    def retrieve_results(self, 
                        batch_id: str, 
                        output_directory: Optional[str] = None) -> List[BatchResult]:
        """
        Retrieve and transform OpenAI batch results to our format.
        """
        try:
            batch_job = self.client.batches.retrieve(batch_id)
            
            if batch_job.status != 'completed':
                raise ValueError(f"Batch job {batch_id} is not completed. Status: {batch_job.status}")
            
            result_file_id = batch_job.output_file_id
            
            # Retrieve with retries
            max_retries = 3
            retry_delay = 2
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    result_content = self.client.files.content(result_file_id).content
                    if not result_content or len(result_content) == 0:
                        raise ValueError("Retrieved empty content from batch results")
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"Retry {attempt + 1}/{max_retries}: Failed to retrieve batch results: {e}")
                        time.sleep(retry_delay)
                    else:
                        raise RuntimeError(f"Failed to retrieve batch results after {max_retries} attempts: {last_error}")
            
            # Save raw results if directory provided
            if output_directory:
                batch_dir = Path(output_directory) / "batch"
                ensure_directory_exists(batch_dir)
                result_file_path = batch_dir / f"{batch_id}_results.jsonl"
                with open(result_file_path, 'wb') as f:
                    f.write(result_content)
            
            # Parse results and transform to our format
            batch_results = []
            lines = result_content.decode('utf-8').strip().split('\n')
            
            for line_num, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        # Transform OpenAI format to our BatchResult format
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] JSON parsing error on line {line_num}: {e}")
                        # Create error result for this line
                        batch_results.append(BatchResult(
                            custom_id=f"error_line_{line_num}",
                            content=None,
                            success=False,
                            error=f"JSON parsing error: {e}",
                            metadata={"line_number": line_num, "raw_line": line[:500]}
                        ))
            
            return batch_results
            
        except Exception as e:
            raise RuntimeError(f"Error retrieving OpenAI batch results: {e}")
    
    def compile_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Compile schema to OpenAI's format."""
        # Use the existing compile_unified_schema function
        return compile_unified_schema(schema_dict, 'openai')
    
    def get_supported_models(self) -> List[str]:
        """List of OpenAI models that support batch processing."""
        return [
            "gpt-4o",
            "gpt-4o-mini", 
            "gpt-4-turbo",
            "gpt-4-turbo-preview",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k",
            "gpt-4.1-mini"
        ]
    
    def supports_schema_validation(self) -> bool:
        """OpenAI supports JSON schema validation."""
        return True