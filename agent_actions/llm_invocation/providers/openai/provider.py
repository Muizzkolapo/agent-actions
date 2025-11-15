"""
OpenAI Batch API provider implementation.

This module implements the BatchProvider interface for OpenAI's Batch API,
handling the transformation between our standardized format and OpenAI's
specific requirements.
"""
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from openai import OpenAI
from ..base import BatchProvider, BatchTask, BatchResult

class OpenAIBatchProvider(BatchProvider):
    """
    OpenAI Batch API implementation of the BatchProvider interface.
    
    Handles format transformations:
    - Input: BatchTask → OpenAI task format
    - Output: OpenAI response → BatchResult
    """

    def __init__(self, api_key: Optional[str]=None):
        """Initialize OpenAI client."""
        self.client = OpenAI(api_key=api_key)

    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
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
        model_name = batch_task.model_config.get('model_name', 'gpt-4o-mini')
        body = {'model': model_name, 'messages': [{'role': 'system', 'content': batch_task.prompt}, {'role': 'user', 'content': batch_task.user_content}]}
        default_temp_only_models = ['gpt-5-mini', 'gpt-5-nano', 'gpt-5']
        if 'temperature' in batch_task.model_config:
            temp_value = batch_task.model_config['temperature']
            if model_name not in default_temp_only_models or temp_value == 1:
                if model_name not in default_temp_only_models:
                    body['temperature'] = temp_value
        if 'max_tokens' in batch_task.model_config and batch_task.model_config['max_tokens'] is not None:
            body['max_tokens'] = batch_task.model_config['max_tokens']
        if schema:
            body['response_format'] = {'type': 'json_schema', 'json_schema': schema}
        return {'custom_id': batch_task.custom_id, 'method': 'POST', 'url': '/v1/chat/completions', 'body': body}

    def _extract_error_from_response(self, raw_response: Dict[str, Any]) -> Optional[str]:
        """Extract error from OpenAI response."""
        if raw_response.get('error'):
            return str(raw_response['error'])
        response_data = raw_response.get('response', {})
        status_code = response_data.get('status_code')
        if status_code and status_code != 200:
            return f"HTTP {status_code}"
        return None

    def _extract_content_from_response(self, raw_response: Dict[str, Any]) -> Any:
        """Extract content from OpenAI response."""
        response_data = raw_response.get('response', {})
        response_body = response_data.get('body', {})
        if 'choices' in response_body and response_body['choices']:
            choice = response_body['choices'][0]
            if 'message' in choice and 'content' in choice['message']:
                return choice['message']['content']
        return None

    def _extract_metadata_from_response(self, raw_response: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metadata from OpenAI response."""
        response_data = raw_response.get('response', {})
        response_body = response_data.get('body', {})
        return {
            'model': response_body.get('model'),
            'finish_reason': response_body.get('choices', [{}])[0].get('finish_reason'),
            'created': response_body.get('created'),
            'system_fingerprint': response_body.get('system_fingerprint'),
            'status_code': response_data.get('status_code')
        }

    def _extract_usage_from_response(self, raw_response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract usage from OpenAI response."""
        response_data = raw_response.get('response', {})
        response_body = response_data.get('body', {})
        return response_body.get('usage')

    def _get_default_model(self) -> str:
        """Return OpenAI's default model."""
        return 'gpt-4o-mini'

    def _prepare_batch_input_file(self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str) -> Path:
        """Write tasks to JSONL file for OpenAI."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, 'openai')

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> Tuple[str, str]:
        """Submit batch to OpenAI API."""
        batch_file = self.client.files.create(file=open(input_file, 'rb'), purpose='batch')
        batch_job = self.client.batches.create(input_file_id=batch_file.id, endpoint='/v1/chat/completions', completion_window='24h')
        print(f'OpenAI batch job created with ID: {batch_job.id}')
        print(f'Status: {batch_job.status}')
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
        return f'{batch_id}_results.jsonl'

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Fetch raw results from OpenAI API."""
        batch_job = self.client.batches.retrieve(batch_id)
        if batch_job.status != 'completed':
            from agent_actions.shared.exceptions import ValidationError
            raise ValidationError('Batch job is not completed', context={'batch_id': batch_id, 'status': batch_job.status, 'vendor': 'openai'})

        result_file_id = batch_job.output_file_id
        result_content = self.client.files.content(result_file_id).content

        if not result_content or len(result_content) == 0:
            from agent_actions.shared.exceptions import VendorAPIError
            raise VendorAPIError(vendor='openai', endpoint='files.content', context={'message': 'Retrieved empty content from batch results', 'batch_id': batch_id, 'result_file_id': result_file_id})

        return result_content