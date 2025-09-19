"""
Gemini Batch API provider implementation.

This module implements the BatchProvider interface for Google's Gemini Batch API,
handling the transformation between our standardized format and Gemini's
specific requirements.
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    types = None

from ..base import BatchProvider, BatchTask, BatchResult
from agent_actions.core.utils.path_utils import ensure_directory_exists
from agent_actions.core.parser.schema_change import compile_unified_schema


class GeminiBatchProvider(BatchProvider):
    """
    Gemini Batch API implementation of the BatchProvider interface.
    
    Handles format transformations:
    - Input: BatchTask → Gemini task format
    - Output: Gemini response → BatchResult
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Gemini client."""
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-genai package is not installed. "
                "Install it with: pip install google-genai"
            )
        
        self.client = genai.Client(
            api_key=api_key,
            http_options={'api_version': 'v1alpha'}
        )
        
    def format_task_for_provider(self, 
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        # Combine system prompt and user content
        combined_text = f"{batch_task.prompt}\n\n{batch_task.user_content}"
        
        # Build generation config from model_config
        generation_config = {}
        if "temperature" in batch_task.model_config:
            generation_config["temperature"] = batch_task.model_config["temperature"]
        if "max_tokens" in batch_task.model_config:
            generation_config["max_tokens"] = batch_task.model_config["max_tokens"]
        
        # Add native schema support for structured output
        if schema:
            request["response_schema"] = schema
            request["response_mime_type"] = "application/json"
        
        request = {
            "contents": [{
                "parts": [{
                    "text": combined_text
                }]
            }]
        }
        
        # Only add generation_config if it has values
        if generation_config:
            request["generation_config"] = generation_config
        
        return {
            "key": batch_task.custom_id,
            "request": request
        }
    
    def parse_provider_response(self, raw_response: Dict[str, Any]) -> BatchResult:
        """
        Transform Gemini's response format to our standardized BatchResult.
        
        Gemini returns:
        {
            "response": {
                "responseId": "abc123",
                "modelVersion": "gemini-2.5-flash",
                "candidates": [{
                    "content": {
                        "role": "model",
                        "parts": [{
                            "text": "response text"
                        }]
                    },
                    "finishReason": "STOP",
                    "index": 0
                }],
                "usageMetadata": {
                    "totalTokenCount": 100,
                    "promptTokenCount": 20,
                    "candidatesTokenCount": 80
                }
            },
            "key": "request-1"
        }
        """
        custom_id = raw_response.get("key", "unknown")
        
        # Check for errors (Gemini might return errors differently)
        if "error" in raw_response:
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=str(raw_response["error"]),
                metadata={"raw_error": raw_response["error"]}
            )
        
        response_data = raw_response.get("response", {})
        
        # Extract content from candidates
        content = None
        candidates = response_data.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            candidate_content = candidate.get("content", {})
            parts = candidate_content.get("parts", [])
            
            if parts:
                # Handle text responses
                text_content = parts[0].get("text", "")
                
                # Try to parse as JSON if it looks like JSON
                try:
                    content = json.loads(text_content)
                except json.JSONDecodeError:
                    content = text_content
                
                # Note: Multimodal responses (images) could be handled here in the future
                # if parts[0].get("inlineData"):
                #     # Handle image data
        
        # Build metadata
        metadata = {
            "model_version": response_data.get("modelVersion"),
            "response_id": response_data.get("responseId"),
            "finish_reason": candidates[0].get("finishReason") if candidates else None,
        }
        
        # Extract usage data
        usage_metadata = response_data.get("usageMetadata", {})
        usage = {
            "total_tokens": usage_metadata.get("totalTokenCount"),
            "prompt_tokens": usage_metadata.get("promptTokenCount"),
            "completion_tokens": usage_metadata.get("candidatesTokenCount")
        }
        
        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=bool(content is not None),
            error=None if content is not None else "No content in response",
            metadata=metadata,
            usage=usage
        )
    
    def prepare_tasks(self, 
                     data: List[Dict[str, Any]], 
                     agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data to Gemini batch format.
        
        This method orchestrates the transformation of multiple data items
        into Gemini-formatted tasks.
        """
        tasks = []
        
        # Get schema if configured
        schema = agent_config.get("compiled_schema")
        
        for row in data:
            # Create BatchTask from row data
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=row.get("prompt", agent_config.get("prompt", "")),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", "gemini-2.5-flash"),
                    "temperature": agent_config.get("temperature", 0.1),
                    "max_tokens": agent_config.get("max_tokens")
                },
                metadata=row
            )
            
            # Transform to Gemini format
            gemini_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(gemini_task)
        
        return tasks
    
    def submit_batch(self, 
                    tasks: List[Dict[str, Any]], 
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """Submit batch job to Gemini."""
        # Create batch directory
        if output_directory:
            batch_dir = Path(output_directory) / "batch"
        else:
            batch_dir = Path.cwd() / "batch"
        
        ensure_directory_exists(batch_dir)
        
        # Write tasks to JSON file (one task per line for JSONL format)
        file_name = f"{Path(batch_name).stem}_batch_input.json"
        file_path = batch_dir / file_name
        
        with open(file_path, 'w') as file:
            for task in tasks:
                file.write(json.dumps(task) + '\n')
        
        print(f"Gemini batch file created at: {file_path}")
        
        # Upload file to Gemini
        try:
            print(f"Uploading file: {file_path}")
            uploaded_file = self.client.files.upload(
                file=str(file_path),
                config=types.UploadFileConfig(
                    display_name=f'{batch_name}-batch-input'
                )
            )
            print(f"Uploaded file: {uploaded_file.name}")
            
            # Create batch job
            # Get model name from first task
            model_name = "gemini-2.5-flash"  # Default
            if tasks and "model_name" in tasks[0].get("request", {}).get("generation_config", {}):
                model_name = tasks[0]["request"]["generation_config"]["model_name"]
            elif hasattr(self, '_last_model_name'):
                model_name = self._last_model_name
            
            batch_job = self.client.batches.create(
                model=model_name,
                src=uploaded_file.name,
                config={
                    'display_name': batch_name,
                }
            )
            
            print(f"Gemini batch job created with ID: {batch_job.name}")
            return batch_job.name
            
        except Exception as e:
            from agent_actions.core.exceptions import GeminiError
            raise GeminiError("batch_submission", cause=e)
    
    def check_status(self, batch_id: str) -> str:
        """Check Gemini batch job status."""
        try:
            batch_job = self.client.batches.get(name=batch_id)
            
            # Map Gemini status to our expected status values
            status_mapping = {
                'JOB_STATE_PENDING': 'in_progress',
                'JOB_STATE_RUNNING': 'in_progress', 
                'JOB_STATE_SUCCEEDED': 'completed',
                'JOB_STATE_FAILED': 'failed',
                'JOB_STATE_CANCELLED': 'cancelled'
            }
            
            gemini_status = batch_job.state.name
            return status_mapping.get(gemini_status, gemini_status.lower())
            
        except Exception as e:
            from agent_actions.core.exceptions import GeminiError
            raise GeminiError("batch_status", cause=e)
    
    def retrieve_results(self, 
                        batch_id: str, 
                        output_directory: Optional[str] = None) -> List[BatchResult]:
        """
        Retrieve and transform Gemini batch results to our format.
        """
        try:
            batch_job = self.client.batches.get(name=batch_id)
            
            if batch_job.state.name != 'JOB_STATE_SUCCEEDED':
                raise ValueError(f"Batch job {batch_id} is not completed. Status: {batch_job.state.name}")
            
            # Get the output file
            result_file_name = batch_job.dest.file_name
            if not result_file_name:
                raise ValueError(f"Batch job {batch_id} has no output file")
            
            print(f"Results are in file: {result_file_name}")
            
            # Download results with retries
            max_retries = 3
            retry_delay = 2
            last_error = None
            result_content = None
            
            for attempt in range(max_retries):
                try:
                    print(f"Downloading result file content (attempt {attempt + 1}/{max_retries})...")
                    file_content_bytes = self.client.files.download(file=result_file_name)
                    result_content = file_content_bytes.decode('utf-8')
                    
                    if not result_content or len(result_content) == 0:
                        raise ValueError("Retrieved empty content from batch results")
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        print(f"Retry {attempt + 1}/{max_retries}: Failed to retrieve batch results: {e}")
                        time.sleep(retry_delay)
                    else:
                        from agent_actions.core.exceptions import GeminiError
                        raise GeminiError("batch_results", context={"max_retries": max_retries, "last_error": str(last_error)}, cause=last_error)
            
            # Save raw results if directory provided
            if output_directory:
                batch_dir = Path(output_directory) / "batch"
                ensure_directory_exists(batch_dir)
                result_file_path = batch_dir / f"{batch_id.replace('/', '_')}_results.jsonl"
                with open(result_file_path, 'w') as f:
                    f.write(result_content)
                print(f"Saved raw results to: {result_file_path}")
            
            # Parse results and transform to our format
            batch_results = []
            lines = result_content.strip().split('\n')
            
            for line_num, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        # Transform Gemini format to our BatchResult format
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
            from agent_actions.core.exceptions import GeminiError
            raise GeminiError("batch_results", cause=e)
    
    def compile_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compile schema to Gemini's format.
        
        Gemini uses response_schema with responseJsonSchema format.
        """
        # Gemini expects the schema directly in OpenAPI/JSON Schema format
        return schema_dict
    
    def get_supported_models(self) -> List[str]:
        """List of Gemini models that support batch processing."""
        return [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-preview-image-generation"
        ]
    
    def supports_schema_validation(self) -> bool:
        """Gemini supports native schema validation via response_schema."""
        return True
    
    def validate_config(self, agent_config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate that the agent configuration is compatible with Gemini.
        
        Also store the model name for later use in submit_batch.
        """
        model_name = agent_config.get('model_name')
        if model_name:
            # Store for use in submit_batch
            self._last_model_name = model_name
            
            if model_name not in self.get_supported_models():
                return False, f"Model '{model_name}' not supported by Gemini batch API"
        
        return True, None