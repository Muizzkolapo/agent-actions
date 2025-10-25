"""
Anthropic Batch API provider implementation.

This module implements the BatchProvider interface for Anthropic's API,
handling the transformation between our standardized format and Anthropic's
specific requirements.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..base import BatchProvider, BatchTask, BatchResult

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

    def __init__(self, api_key: Optional[str]=None, version: Optional[str]=None, enable_prompt_caching: bool=False):
        """
        Initialize Anthropic client with optional configuration.
        
        Args:
            api_key: Anthropic API key
            version: API version header (e.g., "2023-06-01")
            enable_prompt_caching: Whether to enable prompt caching feature
        """
        self.version = version or '2023-06-01'
        self.enable_prompt_caching = enable_prompt_caching
        try:
            import anthropic
            self.anthropic = anthropic
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)
            else:
                self.client = anthropic.Anthropic()
        except ImportError as e:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError('Required package not installed', context={'package': 'anthropic', 'install_command': 'pip install anthropic'}, cause=e)
        except Exception as e:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError('Failed to initialize Anthropic client', context={'provider': 'anthropic', 'error': str(e), 'api_key_source': 'environment variable or parameter'}, cause=e)

    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
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
        messages = [{'role': 'user', 'content': batch_task.user_content}]
        params = {'model': batch_task.model_config.get('model_name', 'claude-3-5-sonnet-20241022'), 'messages': messages}
        if batch_task.prompt:
            params['system'] = batch_task.prompt
        self._add_optional_param(params, 'temperature', batch_task.model_config.get('temperature'))
        self._add_optional_param(params, 'max_tokens', batch_task.model_config.get('max_tokens'), default=4096)
        if schema:
            tools = self._create_json_tool_from_schema(schema)
            if tools:
                tool_name = tools[0]['name']
                params['tools'] = tools
                params['tool_choice'] = {'type': 'tool', 'name': tool_name}
                print(f'🛠️ Added tools for structured JSON output: {len(tools)} tools')
                print(f'🎯 Tool choice set to: {tool_name}')
            else:
                print('⚠️ Schema provided but no tools created')
        else:
            print('ℹ️ No schema provided - using regular text mode')
        if self.enable_prompt_caching:
            params['extra_headers'] = {'anthropic-beta': 'prompt-caching-2024-07-31'}
        return {'custom_id': batch_task.custom_id, 'params': params}

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
        if hasattr(raw_response, 'custom_id'):
            custom_id = raw_response.custom_id
            result = raw_response.result
        elif isinstance(raw_response, dict):
            custom_id = raw_response.get('custom_id', 'unknown')
            result = raw_response.get('result', {})
        else:
            return BatchResult(custom_id='unknown', content=None, success=False, error='Invalid response format from Anthropic', metadata={'raw_response': str(raw_response)})
        result_type = getattr(result, 'type', None) or result.get('type')
        if result_type == 'failed':
            error_info = getattr(result, 'error', None) or result.get('error', {})
            error_message = str(error_info) if error_info else 'Batch processing failed'
            return BatchResult(custom_id=custom_id, content=None, success=False, error=error_message, metadata={'result_type': result_type, 'error_info': error_info})
        elif result_type == 'succeeded':
            message = getattr(result, 'message', None) or result.get('message', {})
            content = None
            if hasattr(message, 'content'):
                content_list = message.content
            else:
                content_list = message.get('content', [])
            if content_list and isinstance(content_list, list):
                tool_use_content = None
                text_content = None
                for content_block in content_list:
                    if hasattr(content_block, 'type') and content_block.type == 'tool_use':
                        tool_name = getattr(content_block, 'name', '')
                        if hasattr(content_block, 'input'):
                            tool_use_content = content_block.input
                            if hasattr(tool_use_content, 'model_dump'):
                                tool_use_content = tool_use_content.model_dump()
                            print(f'🔧 Found tool use: {tool_name}')
                    elif isinstance(content_block, dict) and content_block.get('type') == 'tool_use':
                        tool_name = content_block.get('name', '')
                        tool_use_content = content_block.get('input', {})
                        print(f'🔧 Found tool use: {tool_name}')
                    elif hasattr(content_block, 'type') and content_block.type == 'text':
                        if hasattr(content_block, 'text'):
                            text_content = content_block.text
                    elif isinstance(content_block, dict) and content_block.get('type') == 'text':
                        text_content = content_block.get('text', '')
                    elif hasattr(content_block, 'text'):
                        text_content = content_block.text
                    elif isinstance(content_block, dict) and 'text' in content_block:
                        text_content = content_block['text']
                if tool_use_content is not None:
                    print(f'✅ Extracted structured JSON from tool use')
                    print(f'   Tool content type: {type(tool_use_content)}')
                    print(f"   Tool content keys: {(list(tool_use_content.keys()) if isinstance(tool_use_content, dict) else 'N/A')}")
                    content = tool_use_content
                elif text_content is not None:
                    print(f'📝 Got text response (no tool use): {(text_content[:100] if len(text_content) > 100 else text_content)}...')
                    try:
                        content = json.loads(text_content)
                        print(f'   Successfully parsed text as JSON')
                    except json.JSONDecodeError:
                        content = text_content
                        print(f'   Keeping as plain text')
                else:
                    content_item = content_list[0]
                    if hasattr(content_item, 'type') and hasattr(content_item, 'input'):
                        if content_item.type == 'tool_use':
                            print(f"⚠️ Found uncaught tool use block: {getattr(content_item, 'name', 'unknown')}")
                            content = content_item.input
                            if hasattr(content, 'model_dump'):
                                content = content.model_dump()
                    elif hasattr(content_item, 'text'):
                        content_str = content_item.text
                        try:
                            content = json.loads(content_str)
                        except json.JSONDecodeError:
                            content = content_str
                    elif isinstance(content_item, dict) and 'text' in content_item:
                        content_str = content_item['text']
                        try:
                            content = json.loads(content_str)
                        except json.JSONDecodeError:
                            content = content_str
                    else:
                        class_name = content_item.__class__.__name__ if hasattr(content_item, '__class__') else ''
                        if 'ToolUseBlock' in class_name:
                            print(f'⚠️ Found ToolUseBlock via class name check')
                            if hasattr(content_item, 'input'):
                                content = content_item.input
                                if hasattr(content, 'model_dump'):
                                    content = content.model_dump()
                            else:
                                content = str(content_item)
                        else:
                            content = str(content_item)
            else:
                content = content_list
            if hasattr(message, 'usage'):
                usage = message.usage
                if hasattr(usage, 'model_dump'):
                    usage = usage.model_dump()
            else:
                usage = message.get('usage')
            metadata = {'model': getattr(message, 'model', None) or message.get('model'), 'stop_reason': getattr(message, 'stop_reason', None) or message.get('stop_reason'), 'anthropic_version': self.version, 'result_type': result_type}
            return BatchResult(custom_id=custom_id, content=content, success=True, error=None, metadata=metadata, usage=usage)
        else:
            return BatchResult(custom_id=custom_id, content=None, success=False, error=f'Unknown result type: {result_type}', metadata={'result_type': result_type, 'raw_result': str(result)})

    def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data to Anthropic batch format.

        This method orchestrates the transformation of multiple data items
        into Anthropic-formatted tasks.
        """
        tasks = []
        json_mode = agent_config.get('json_mode', True)
        schema = agent_config.get('compiled_schema') if json_mode else None
        if schema:
            print(f'🔧 Anthropic provider using schema (json_mode: {json_mode}): {schema}')
        else:
            print(f'ℹ️ Anthropic provider: No schema (json_mode: {json_mode}), using regular text mode')
        for row in data:
            batch_task = BatchTask(custom_id=row.get('target_id', row.get('id', '')), prompt=row.get('prompt', agent_config.get('prompt', '')), user_content=json.dumps(row.get('content', row)), model_config={'model_name': agent_config.get('model_name', 'claude-3-sonnet-20240229'), 'temperature': agent_config.get('temperature', 0.1), 'max_tokens': agent_config.get('max_tokens', 1024)}, metadata=row)
            anthropic_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(anthropic_task)
        return tasks

    def submit_batch(self, tasks: List[Dict[str, Any]], batch_name: str, output_directory: Optional[str]=None) -> str:
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
            batch_dir = self._get_batch_directory(output_directory)
            file_name = f'{Path(batch_name).stem}_anthropic_batch_input.json'
            file_path = batch_dir / file_name
            with open(file_path, 'w') as file:
                json.dump({'requests': tasks}, file, indent=2)
            print(f'Anthropic batch input saved at: {file_path}')
            print(f'Submitting batch with {len(tasks)} tasks to Anthropic...')
            batch_response = self.client.messages.batches.create(requests=tasks)
            batch_id = batch_response.id
            print(f'✅ Anthropic batch job created with ID: {batch_id}')
            print(f'Status: {batch_response.processing_status}')
            return batch_id
        except self.anthropic.APIError as e:
            error_msg = f'Anthropic API error during batch submission: {str(e)}'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic API error during batch submission', context={'operation': 'batch_submission', 'batch_name': batch_name, 'task_count': len(tasks)}, cause=e)
        except self.anthropic.AuthenticationError as e:
            error_msg = f'Anthropic authentication failed: {str(e)}. Check your API key.'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic authentication failed during batch submission', context={'operation': 'batch_submission', 'batch_name': batch_name, 'error': 'Check your API key'}, cause=e)
        except Exception as e:
            error_msg = f'Failed to submit batch to Anthropic: {str(e)}'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Failed to submit batch to Anthropic', context={'operation': 'batch_submission', 'batch_name': batch_name}, cause=e)

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
            anthropic_status = batch_info.processing_status
            status_mapping = {'in_progress': 'in_progress', 'ended': 'completed', 'failed': 'failed', 'cancelled': 'cancelled', 'expired': 'failed'}
            return status_mapping.get(anthropic_status, anthropic_status)
        except self.anthropic.APIError as e:
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic API error checking batch status', context={'operation': 'batch_status', 'batch_id': batch_id, 'status_code': getattr(e, 'status_code', None)}, cause=e)
        except self.anthropic.AuthenticationError as e:
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic authentication error', context={'operation': 'authentication', 'batch_id': batch_id, 'auth_error': str(e)}, cause=e)
        except Exception as e:
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Failed to check batch status', context={'operation': 'batch_status', 'batch_id': batch_id}, cause=e)

    def retrieve_results(self, batch_id: str, output_directory: Optional[str]=None) -> List[BatchResult]:
        """
        Retrieve and transform Anthropic batch results to our format.
        
        Args:
            batch_id: Anthropic batch job ID
            output_directory: Optional directory for caching results
            
        Returns:
            List of BatchResult objects
        """
        try:
            status = self.check_status(batch_id)
            if status != 'completed':
                print(f'Batch {batch_id} is not completed. Status: {status}')
                return []
            print(f'Retrieving results for Anthropic batch {batch_id}...')
            results_stream = self.client.messages.batches.results(batch_id)
            batch_results = []
            raw_entries = []
            for entry in results_stream:
                batch_result = self.parse_provider_response(entry)
                batch_results.append(batch_result)
                if hasattr(entry, 'model_dump'):
                    raw_entries.append(entry.model_dump())
                elif hasattr(entry, '__dict__'):
                    raw_entries.append(entry.__dict__)
                else:
                    raw_entries.append(entry)
            print(f'✅ Retrieved {len(batch_results)} results from Anthropic batch {batch_id}')
            if output_directory and raw_entries:
                batch_dir = self._get_batch_directory(output_directory)
                raw_results_file = batch_dir / f'{batch_id}_anthropic_raw_results.jsonl'
                with open(raw_results_file, 'w') as f:
                    for entry in raw_entries:
                        f.write(json.dumps(entry) + '\n')
                print(f'Raw results saved to: {raw_results_file}')
            return batch_results
        except self.anthropic.APIError as e:
            error_msg = f'Anthropic API error retrieving batch results: {str(e)}'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic API error retrieving batch results', context={'operation': 'retrieve_results', 'batch_id': batch_id}, cause=e)
        except self.anthropic.AuthenticationError as e:
            error_msg = f'Anthropic authentication failed: {str(e)}. Check your API key.'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Anthropic authentication failed during retrieve results', context={'operation': 'retrieve_results', 'batch_id': batch_id, 'error': 'Check your API key'}, cause=e)
        except Exception as e:
            error_msg = f'Failed to retrieve Anthropic batch results: {str(e)}'
            print(f'❌ {error_msg}')
            from agent_actions.shared.exceptions import AnthropicError
            raise AnthropicError('Failed to retrieve Anthropic batch results', context={'operation': 'retrieve_results', 'batch_id': batch_id}, cause=e)

    def _create_json_tool_from_schema(self, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Create an Anthropic tool definition from a JSON schema to force structured output.
        
        Args:
            schema: JSON schema dictionary or list of schema objects from BatchService
            
        Returns:
            List containing tool definition for structured JSON response
        """
        actual_schema = None
        tool_name = 'json_response'
        schema_description = 'Provide a structured JSON response'
        if isinstance(schema, list) and len(schema) > 0:
            schema_obj = schema[0]
            if isinstance(schema_obj, dict):
                actual_schema = schema_obj.get('input_schema', {})
                tool_name = schema_obj.get('name', 'json_response').lower().replace('schema', '_response')
                schema_description = schema_obj.get('description', schema_description)
                print(f"🔧 Processing schema from list format: {schema_obj.get('name', 'Unknown')}")
        elif isinstance(schema, dict) and ('properties' in schema or 'type' in schema):
            actual_schema = schema
            schema_description = schema.get('description', schema_description)
            print(f'🔧 Processing direct schema format')
        else:
            print(f'⚠️ Unsupported schema format: {type(schema)} - {schema}')
            return []
        if not actual_schema:
            print(f'⚠️ No valid schema found in: {schema}')
            return []
        properties = actual_schema.get('properties', {})
        required = actual_schema.get('required', [])
        if not properties:
            print(f'⚠️ No properties found in schema: {actual_schema}')
            tool_schema = {'type': 'object', 'properties': {'response': {'type': 'string', 'description': 'The response content'}}, 'required': ['response']}
        else:
            tool_schema = {'type': 'object', 'properties': properties, 'required': required}
            print(f'✅ Created tool schema with properties: {list(properties.keys())}')
        tool_definition = {'name': tool_name, 'description': f'Provide structured JSON output: {schema_description}', 'input_schema': tool_schema}
        print(f"🛠️ Created tool definition: {tool_definition['name']}")
        return [tool_definition]

    def validate_config(self, agent_config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate that the agent configuration is compatible with Anthropic.
        
        Args:
            agent_config: Agent configuration to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        is_valid, error_msg = super().validate_config(agent_config)
        if not is_valid:
            return (is_valid, error_msg)
        anthropic_version = agent_config.get('anthropic_version')
        if anthropic_version and (not isinstance(anthropic_version, str)):
            return (False, 'anthropic_version must be a string')
        enable_prompt_caching = agent_config.get('enable_prompt_caching')
        if enable_prompt_caching is not None and (not isinstance(enable_prompt_caching, bool)):
            return (False, 'enable_prompt_caching must be a boolean')
        return (True, None)