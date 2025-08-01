"""
Anthropic Batch API provider implementation.

This module implements the BatchProvider interface for Anthropic's API,
handling the transformation between our standardized format and Anthropic's
specific requirements.
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from .base import BatchProvider, BatchTask, BatchResult
from ..utils.path_utils import ensure_directory_exists
from ..models.schema_change import compile_unified_schema


class AnthropicBatchProvider(BatchProvider):
    """
    Anthropic Message Batches API implementation of the BatchProvider interface.
    
    This provider integrates with Anthropic's Message Batches API to enable
    batch processing of Claude model requests. It handles format transformations:
    - Input: BatchTask → Anthropic batch request format with custom_id and params
    - Output: Anthropic batch response → BatchResult
    
    Supports all Claude models available through the Message Batches API including:
    - Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus, etc.
    
    Features:
    - Real-time batch status checking
    - Structured response parsing
    - Proper error handling for API failures
    - Support for prompt caching (when enabled)
    """
    
    def __init__(self, api_key: Optional[str] = None, version: Optional[str] = None, 
                 enable_prompt_caching: bool = False):
        """
        Initialize Anthropic client with optional configuration.
        
        Args:
            api_key: Anthropic API key
            version: API version header (e.g., "2023-06-01")
            enable_prompt_caching: Whether to enable prompt caching feature
        """
        self.version = version or "2023-06-01"
        self.enable_prompt_caching = enable_prompt_caching
        
        try:
            import anthropic
            self.anthropic = anthropic
            
            # Initialize client with provided API key or from environment
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)
            else:
                # Will use ANTHROPIC_API_KEY environment variable
                self.client = anthropic.Anthropic()
                
        except ImportError as e:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Anthropic client: {str(e)}. "
                "Make sure your ANTHROPIC_API_KEY environment variable is set or pass api_key parameter."
            ) from e
        
    def format_task_for_provider(self, 
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Transform our BatchTask to Anthropic's Message Batches API format.
        
        Anthropic Message Batches API expects:
        {
            "custom_id": "my-first-request",
            "params": {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": "Hello, world"}
                ]
            }
        }
        """
        messages = []
        
        # Add system message if prompt exists
        if batch_task.prompt:
            messages.append({
                "role": "system", 
                "content": batch_task.prompt
            })
        
        # Add user content
        messages.append({
            "role": "user",
            "content": batch_task.user_content
        })
        
        params = {
            "model": batch_task.model_config.get("model_name", "claude-3-5-sonnet-20241022"),
            "max_tokens": batch_task.model_config.get("max_tokens", 1024),
            "messages": messages
        }
        
        # Add optional parameters from model_config
        if "temperature" in batch_task.model_config:
            params["temperature"] = batch_task.model_config["temperature"]
            
        # Add Anthropic-specific options
        if self.enable_prompt_caching:
            # Add prompt caching if enabled
            params["extra_headers"] = {"anthropic-beta": "prompt-caching-2024-07-31"}
        
        return {
            "custom_id": batch_task.custom_id,
            "params": params
        }
    
    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """
        Transform Anthropic's batch response format to our standardized BatchResult.
        
        Anthropic returns results in this format:
        {
            "custom_id": "my-first-request",
            "result": {
                "type": "succeeded",  # or "failed"
                "message": {
                    "content": [{"type": "text", "text": "Response text"}],
                    "role": "assistant",
                    "model": "claude-3-opus-20240229",
                    "stop_reason": "end_turn",
                    "usage": {...}
                }
            }
        }
        """
        # Handle both dict and object responses from Anthropic SDK
        if hasattr(raw_response, 'custom_id'):
            # SDK object
            custom_id = raw_response.custom_id
            result = raw_response.result
        elif isinstance(raw_response, dict):
            # Dict format
            custom_id = raw_response.get("custom_id", "unknown")
            result = raw_response.get("result", {})
        else:
            return BatchResult(
                custom_id="unknown",
                content=None,
                success=False,
                error="Invalid response format from Anthropic",
                metadata={"raw_response": str(raw_response)}
            )
        
        # Check if the result succeeded
        result_type = getattr(result, 'type', None) or result.get('type')
        
        if result_type == 'failed':
            # Handle failed results
            error_info = getattr(result, 'error', None) or result.get('error', {})
            error_message = str(error_info) if error_info else "Batch processing failed"
            
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=error_message,
                metadata={"result_type": result_type, "error_info": error_info}
            )
        
        elif result_type == 'succeeded':
            # Handle successful results
            message = getattr(result, 'message', None) or result.get('message', {})
            
            # Extract content from message
            content = None
            if hasattr(message, 'content'):
                content_list = message.content
            else:
                content_list = message.get('content', [])
            
            if content_list and isinstance(content_list, list):
                # Anthropic returns content as a list of content blocks
                content_item = content_list[0]
                if hasattr(content_item, 'text'):
                    content_str = content_item.text
                elif isinstance(content_item, dict) and 'text' in content_item:
                    content_str = content_item['text']
                else:
                    content_str = str(content_item)
                
                # Try to parse as JSON if it looks like structured output
                try:
                    content = json.loads(content_str)
                except json.JSONDecodeError:
                    content = content_str
            else:
                content = content_list
            
            # Extract usage information
            if hasattr(message, 'usage'):
                usage = message.usage
                if hasattr(usage, 'model_dump'):
                    usage = usage.model_dump()
            else:
                usage = message.get('usage')
            
            # Build metadata
            metadata = {
                "model": getattr(message, 'model', None) or message.get('model'),
                "stop_reason": getattr(message, 'stop_reason', None) or message.get('stop_reason'),
                "anthropic_version": self.version,
                "result_type": result_type
            }
            
            return BatchResult(
                custom_id=custom_id,
                content=content,
                success=True,
                error=None,
                metadata=metadata,
                usage=usage
            )
        
        else:
            # Unknown result type
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=f"Unknown result type: {result_type}",
                metadata={"result_type": result_type, "raw_result": str(result)}
            )
    
    def prepare_tasks(self, 
                     data: List[Dict[str, Any]], 
                     agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data to Anthropic batch format.
        
        This method orchestrates the transformation of multiple data items
        into Anthropic-formatted tasks.
        """
        tasks = []
        
        # Get schema if configured
        schema = None
        if agent_config.get("schema_name"):
            # This would normally load from schema files
            # For now, we'll assume it's passed in the config
            schema = agent_config.get("compiled_schema")
        
        for row in data:
            # Create BatchTask from row data
            batch_task = BatchTask(
                custom_id=row.get("target_id", row.get("id", "")),
                prompt=agent_config.get("prompt", ""),
                user_content=json.dumps(row.get("content", row)),
                model_config={
                    "model_name": agent_config.get("model_name", "claude-3-sonnet-20240229"),
                    "temperature": agent_config.get("temperature", 0.1),
                    "max_tokens": agent_config.get("max_tokens", 1024)
                },
                metadata=row
            )
            
            # Transform to Anthropic format
            anthropic_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(anthropic_task)
        
        return tasks
    
    def submit_batch(self, 
                    tasks: List[Dict[str, Any]], 
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """
        Submit batch job to Anthropic using the Message Batches API.
        
        Args:
            tasks: List of tasks formatted for Anthropic API
            batch_name: Name for the batch job
            output_directory: Optional directory for storing batch-related files
            
        Returns:
            Anthropic batch job ID
        """
        try:
            # Create batch directory for saving reference files
            if output_directory:
                batch_dir = Path(output_directory) / "batch"
            else:
                batch_dir = Path.cwd() / "batch"
            
            ensure_directory_exists(batch_dir)
            
            # Save tasks to JSON file for reference
            file_name = f"{Path(batch_name).stem}_anthropic_batch_input.json"
            file_path = batch_dir / file_name
            
            with open(file_path, 'w') as file:
                json.dump({"requests": tasks}, file, indent=2)
            
            print(f"Anthropic batch input saved at: {file_path}")
            
            # Submit batch to Anthropic API
            print(f"Submitting batch with {len(tasks)} tasks to Anthropic...")
            
            batch_response = self.client.messages.batches.create(
                requests=tasks
            )
            
            batch_id = batch_response.id
            print(f"✅ Anthropic batch job created with ID: {batch_id}")
            print(f"Status: {batch_response.processing_status}")
            
            return batch_id
            
        except self.anthropic.APIError as e:
            error_msg = f"Anthropic API error during batch submission: {str(e)}"
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        except self.anthropic.AuthenticationError as e:
            error_msg = f"Anthropic authentication failed: {str(e)}. Check your API key."
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Failed to submit batch to Anthropic: {str(e)}"
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
    
    def check_status(self, batch_id: str) -> str:
        """
        Check Anthropic batch job status.
        
        Args:
            batch_id: Anthropic batch job ID
            
        Returns:
            Status string ('in_progress', 'completed', 'failed', 'cancelled')
        """
        try:
            batch_info = self.client.messages.batches.retrieve(batch_id)
            
            # Anthropic uses 'processing_status' field
            # Map Anthropic statuses to our standard format
            anthropic_status = batch_info.processing_status
            
            status_mapping = {
                'in_progress': 'in_progress',
                'ended': 'completed',
                'failed': 'failed',
                'cancelled': 'cancelled',
                'expired': 'failed'
            }
            
            return status_mapping.get(anthropic_status, anthropic_status)
            
        except self.anthropic.APIError as e:
            raise RuntimeError(f"Anthropic API error checking batch status: {str(e)}")
        except self.anthropic.AuthenticationError as e:
            raise RuntimeError(f"Anthropic authentication failed: {str(e)}. Check your API key.")
        except Exception as e:
            raise RuntimeError(f"Failed to check Anthropic batch status: {str(e)}")
    
    def retrieve_results(self, 
                        batch_id: str, 
                        output_directory: Optional[str] = None) -> List[BatchResult]:
        """
        Retrieve and transform Anthropic batch results to our format.
        
        Args:
            batch_id: Anthropic batch job ID
            output_directory: Optional directory for caching results
            
        Returns:
            List of BatchResult objects
        """
        try:
            # First check if batch is completed
            status = self.check_status(batch_id)
            if status != 'completed':
                print(f"Batch {batch_id} is not completed. Status: {status}")
                return []
            
            # Retrieve results from Anthropic API
            print(f"Retrieving results for Anthropic batch {batch_id}...")
            results_stream = self.client.messages.batches.results(batch_id)
            
            batch_results = []
            raw_entries = []  # Store raw entries for debugging
            
            # Process each result in the stream
            for entry in results_stream:
                batch_result = self.parse_provider_response(entry)
                batch_results.append(batch_result)
                
                # Store raw entry for debugging
                if hasattr(entry, 'model_dump'):
                    raw_entries.append(entry.model_dump())
                elif hasattr(entry, '__dict__'):
                    raw_entries.append(entry.__dict__)
                else:
                    raw_entries.append(entry)
            
            print(f"✅ Retrieved {len(batch_results)} results from Anthropic batch {batch_id}")
            
            # Save raw results for debugging/reference
            if output_directory and raw_entries:
                batch_dir = Path(output_directory) / "batch"
                ensure_directory_exists(batch_dir)
                
                raw_results_file = batch_dir / f"{batch_id}_anthropic_raw_results.jsonl"
                with open(raw_results_file, 'w') as f:
                    for entry in raw_entries:
                        f.write(json.dumps(entry) + '\n')
                
                print(f"Raw results saved to: {raw_results_file}")
            
            return batch_results
            
        except self.anthropic.APIError as e:
            error_msg = f"Anthropic API error retrieving batch results: {str(e)}"
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        except self.anthropic.AuthenticationError as e:
            error_msg = f"Anthropic authentication failed: {str(e)}. Check your API key."
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"Failed to retrieve Anthropic batch results: {str(e)}"
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
    
    def compile_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compile schema to Anthropic's format.
        
        Anthropic doesn't use strict JSON schema validation like OpenAI.
        Instead, we convert the schema to natural language instructions
        that can be included in the prompt to guide structured output.
        """
        try:
            return compile_unified_schema(schema_dict, 'anthropic')
        except Exception:
            # Fallback: convert schema to natural language description
            if isinstance(schema_dict, dict) and 'properties' in schema_dict:
                description = "Please respond with a JSON object containing the following fields:\n"
                for field, field_info in schema_dict['properties'].items():
                    field_type = field_info.get('type', 'any')
                    field_desc = field_info.get('description', '')
                    description += f"- {field} ({field_type}): {field_desc}\n"
                return {"description": description, "original_schema": schema_dict}
            return schema_dict
    
    def get_supported_models(self) -> List[str]:
        """List of Anthropic models that support batch processing."""
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-sonnet-20240620", 
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
    
    def supports_schema_validation(self) -> bool:
        """
        Whether Anthropic supports JSON schema validation.
        
        Anthropic supports structured output but not strict JSON schema validation
        like OpenAI. It can be guided to produce structured output through prompting.
        """
        return True  # Supports structured output through prompting
    
    def validate_config(self, agent_config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate that the agent configuration is compatible with Anthropic.
        
        Args:
            agent_config: Agent configuration to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Call parent validation first
        is_valid, error_msg = super().validate_config(agent_config)
        if not is_valid:
            return is_valid, error_msg
        
        # Anthropic-specific validation
        anthropic_version = agent_config.get("anthropic_version")
        if anthropic_version and not isinstance(anthropic_version, str):
            return False, "anthropic_version must be a string"
        
        enable_prompt_caching = agent_config.get("enable_prompt_caching")
        if enable_prompt_caching is not None and not isinstance(enable_prompt_caching, bool):
            return False, "enable_prompt_caching must be a boolean"
        
        # Validate model name is supported
        model_name = agent_config.get('model_name')
        if model_name and model_name not in self.get_supported_models():
            return False, f"Model '{model_name}' is not supported by Anthropic batch processing. Supported models: {', '.join(self.get_supported_models())}"
        
        return True, None