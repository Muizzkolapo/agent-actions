"""
Base provider interface for batch processing systems.

This module defines the abstract base class that all batch providers must implement,
enabling support for multiple batch processing backends (OpenAI, custom, etc.).

Key Design Principle:
--------------------
Different providers have different input/output formats, but we intercept and transform
these to match our standardized format. This ensures the rest of the agent-actions
system doesn't need to know about provider-specific details.

Flow:
1. Agent-actions data → BatchTask → Provider-specific format (via format_task_for_provider)
2. Submit to provider
3. Provider-specific response → BatchResult (via parse_provider_response)
4. BatchResult → Agent-actions workflow format

This allows us to add new providers without changing the core workflow logic.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import json

@dataclass
class BatchTask:
    """Provider-agnostic representation of a batch task."""
    custom_id: str
    prompt: str
    user_content: str
    model_config: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class BatchResult:
    """Provider-agnostic representation of a batch result."""
    custom_id: str
    content: Any
    success: bool
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None

class BatchProvider(ABC):
    """
    Abstract base class for batch processing providers.
    
    This interface defines the contract that all batch providers must implement
    to integrate with the agent-actions batch processing system.
    """

    @abstractmethod
    def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data format to provider-specific task format.
        
        This method transforms our standardized format to whatever format
        the specific provider expects.
        
        Args:
            data: List of data items to process, each containing target_id and content
            agent_config: Agent configuration including model_name, prompt, schema_name, etc.
            
        Returns:
            List of provider-specific task dictionaries ready for submission
        """
        pass

    @abstractmethod
    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        """
        Transform standardized BatchTask to provider-specific format.
        
        This method handles the conversion from our internal representation
        to whatever format the provider's API expects.
        
        Args:
            batch_task: Standardized BatchTask object
            schema: Optional compiled schema for structured output
            
        Returns:
            Provider-specific task dictionary
            
        Example:
            BatchTask(custom_id="123", prompt="...", user_content="...")
            
            OpenAI expects:
            {
                "custom_id": "123",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {"messages": [...]}
            }
            
            Another provider might expect:
            {
                "id": "123",
                "request": {
                    "prompt": "...",
                    "input": "..."
                }
            }
        """
        pass

    @abstractmethod
    def submit_batch(self, tasks: List[Dict[str, Any]], batch_name: str, output_directory: Optional[str]=None) -> Tuple[str, str]:
        """
        Submit a batch job to the provider.

        Args:
            tasks: List of provider-specific tasks from prepare_tasks()
            batch_name: Name for the batch job
            output_directory: Optional directory for storing batch-related files

        Returns:
            Tuple of (batch_id, initial_status) where:
            - batch_id: Provider-specific batch job ID
            - initial_status: Initial status from provider (e.g., 'in_progress', 'completed', 'submitted')
        """
        pass

    @abstractmethod
    def check_status(self, batch_id: str) -> str:
        """
        Check the status of a batch job.
        
        Args:
            batch_id: Provider-specific batch job ID
            
        Returns:
            Status string (e.g., 'validating', 'in_progress', 'completed', 'failed')
        """
        pass

    @abstractmethod
    def retrieve_results(self, batch_id: str, output_directory: Optional[str]=None) -> List[BatchResult]:
        """
        Retrieve and parse results from a completed batch job.
        
        This method MUST handle the transformation from provider-specific
        response format to our standardized BatchResult format.
        
        Args:
            batch_id: Provider-specific batch job ID
            output_directory: Optional directory for caching results
            
        Returns:
            List of BatchResult objects containing the processed results
        """
        pass

    @abstractmethod
    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """
        Transform provider-specific response format to standardized BatchResult.
        
        This method handles the interception and processing of different provider
        outputs to match our expected format.
        
        Args:
            raw_response: Provider-specific response object/dict
            
        Returns:
            Standardized BatchResult object
            
        Example:
            OpenAI returns: {"custom_id": "123", "response": {"body": {"choices": [...]}}}
            Another provider returns: {"id": "123", "result": {"data": "..."}}
            Both get transformed to: BatchResult(custom_id="123", content={...}, success=True)
        """
        pass

    def compile_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        DEPRECATED: This method is no longer used for schema compilation.

        Schema compilation is now handled by the unified prepare_schema_unified()
        function in agent_actions.core.parser.schema_change module.

        This method remains for backward compatibility but should not be used.

        Args:
            schema_dict: Generic schema dictionary

        Returns:
            Provider-specific schema format (returns as-is by default)
        """
        return schema_dict

    def get_supported_models(self) -> List[str]:
        """
        Get list of model names supported by this provider.
        
        Returns:
            List of supported model names
        """
        return []

    def validate_config(self, agent_config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate that the agent configuration is compatible with this provider.

        Model validation is delegated to the API provider itself, which will
        return appropriate errors for invalid model names.

        Args:
            agent_config: Agent configuration to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        return (True, None)

    def _get_batch_directory(self, output_directory: Optional[str]=None) -> Path:
        """
        Get or create the batch directory.

        This is OUR code - all providers use the same directory structure.

        Args:
            output_directory: Optional output directory

        Returns:
            Path to batch directory
        """
        from agent_actions.utilities.utils_path_utils import ensure_directory_exists
        if output_directory:
            batch_dir = Path(output_directory) / 'batch'
        else:
            batch_dir = Path.cwd() / 'batch'
        ensure_directory_exists(batch_dir)
        return batch_dir

    def _write_jsonl_file(self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str, provider_name: str) -> Path:
        """
        Write tasks to JSONL file.

        This is OUR code - we chose JSONL format for consistency across providers.

        Args:
            tasks: List of task dictionaries
            batch_dir: Directory to write to
            batch_name: Base name for the file
            provider_name: Provider name for file suffix (e.g., "openai", "ollama")

        Returns:
            Path to created file
        """
        file_name = f'{Path(batch_name).stem}_{provider_name}_batch_input.jsonl'
        file_path = batch_dir / file_name
        with open(file_path, 'w') as file:
            for task in tasks:
                file.write(json.dumps(task) + '\n')
        print(f'{provider_name.title()} batch input file: {file_path}')
        return file_path

    def _read_jsonl_file(self, file_path: Path) -> List[BatchResult]:
        """
        Read JSONL file and parse to BatchResults.

        This is OUR code - we handle JSONL parsing the same way everywhere.

        Args:
            file_path: Path to JSONL file

        Returns:
            List of BatchResult objects
        """
        if not file_path.exists():
            from agent_actions.shared.exceptions import VendorAPIError
            raise VendorAPIError(vendor=self.__class__.__name__, endpoint='retrieve_results', context={'message': 'Batch output file not found', 'expected_path': str(file_path)})
        batch_results = []
        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        print(f'[ERROR] JSON parsing error on line {line_num}: {e}')
                        batch_results.append(BatchResult(custom_id=f'error_line_{line_num}', content=None, success=False, error=f'JSON parsing error: {e}', metadata={'line_number': line_num, 'raw_line': line[:100]}))
        return batch_results

    def _add_optional_param(self, target: Dict[str, Any], key: str, value: Any, default: Any=None) -> None:
        """
        Add parameter to target dict only if value is not None.

        This is OUR code - standardizes optional parameter handling across providers.

        Args:
            target: Dict to add parameter to
            key: Parameter key
            value: Parameter value (only added if not None)
            default: Default value to use if value is None and this is provided
        """
        if value is not None:
            target[key] = value
        elif default is not None:
            target[key] = default