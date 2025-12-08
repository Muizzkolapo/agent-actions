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

    def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert agent-actions data format to provider-specific task format (Template Method).

        This template method provides the common implementation for all providers.
        Providers only need to implement _get_default_model() and optionally _get_default_temperature().

        Args:
            data: List of data items to process, each containing target_id and content
            agent_config: Agent configuration including model_name, prompt, schema_name, etc.

        Returns:
            List of provider-specific task dictionaries ready for submission
        """
        tasks = []
        json_mode = agent_config.get('json_mode', True)
        schema = agent_config.get('compiled_schema') if json_mode else None

        for row in data:
            batch_task = BatchTask(
                custom_id=row.get('target_id', row.get('id', '')),
                prompt=row.get('prompt', agent_config.get('prompt', '')),
                user_content=json.dumps(row.get('content', row)),
                model_config={
                    'model_name': agent_config.get('model_name', self._get_default_model()),
                    'temperature': agent_config.get('temperature', self._get_default_temperature()),
                    'max_tokens': agent_config.get('max_tokens')
                },
                metadata=row
            )
            provider_task = self.format_task_for_provider(batch_task, schema)
            tasks.append(provider_task)

        return tasks

    @abstractmethod
    def _get_default_model(self) -> str:
        """
        Return provider's default model name.

        Subclasses MUST implement this to specify their default model.

        Returns:
            Default model name for this provider
        """
        pass

    def _get_default_temperature(self) -> float:
        """
        Return provider's default temperature.

        Subclasses MAY override this. Default is 0.1.

        Returns:
            Default temperature for this provider
        """
        return 0.1

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

    def submit_batch(self, tasks: List[Dict[str, Any]], batch_name: str, output_directory: Optional[str]=None) -> Tuple[str, str]:
        """
        Submit a batch job to the provider (Template Method).

        This template method provides the common workflow:
        1. Get batch directory
        2. Prepare input file in provider-specific format
        3. Submit to provider API

        Providers implement:
        - _prepare_batch_input_file() - Write tasks to file
        - _submit_to_provider_api() - Call provider API

        Args:
            tasks: List of provider-specific tasks from prepare_tasks()
            batch_name: Name for the batch job
            output_directory: Optional directory for storing batch-related files

        Returns:
            Tuple of (batch_id, initial_status) where:
            - batch_id: Provider-specific batch job ID
            - initial_status: Initial status from provider (e.g., 'in_progress', 'completed', 'submitted')
        """
        import logging
        logger = logging.getLogger(__name__)

        batch_dir = self._get_batch_directory(output_directory)
        input_file = self._prepare_batch_input_file(tasks, batch_dir, batch_name)
        logger.info(f'Submitting batch with {len(tasks)} tasks to {self.__class__.__name__}...')
        return self._submit_to_provider_api(input_file, batch_name)

    def check_status(self, batch_id: str) -> str:
        """
        Check the status of a batch job (Template Method).

        This template method provides common error handling and status normalization.
        Providers implement _fetch_status() and _normalize_status() hooks.

        Args:
            batch_id: Provider-specific batch job ID

        Returns:
            Normalized status string (e.g., 'validating', 'in_progress', 'completed', 'failed')
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            raw_status = self._fetch_status(batch_id)
            return self._normalize_status(raw_status)
        except Exception as e:
            logger.error(f"Error checking batch {batch_id}: {e}")
            raise

    @abstractmethod
    def _fetch_status(self, batch_id: str) -> str:
        """
        Fetch raw status from provider API.

        Subclasses MUST implement this to call their provider's status API.

        Args:
            batch_id: Provider-specific batch job ID

        Returns:
            Raw status string from provider
        """
        pass

    @abstractmethod
    def _normalize_status(self, raw_status: str) -> str:
        """
        Normalize provider-specific status to standard format.

        Subclasses MUST implement this to map their provider's status values
        to our standard set: 'in_progress', 'completed', 'failed', 'cancelled', etc.

        Args:
            raw_status: Raw status from provider

        Returns:
            Normalized status string
        """
        pass

    def retrieve_results(self, batch_id: str, output_directory: Optional[str]=None) -> List[BatchResult]:
        """
        Retrieve and parse results from a completed batch job (Template Method).

        This template method provides the common workflow:
        1. Fetch raw results from provider API (with retry)
        2. Optionally write results to file
        3. Parse results to BatchResult format

        Providers implement:
        - _fetch_raw_results() - Call provider API to get results
        - _get_result_file_name() - Specify result file naming

        Args:
            batch_id: Provider-specific batch job ID
            output_directory: Optional directory for caching results

        Returns:
            List of BatchResult objects containing the processed results
        """
        import logging
        logger = logging.getLogger(__name__)

        # Fetch raw results with retry
        logger.info(f'Retrieving results for batch {batch_id}...')
        raw_results = self._retry_with_backoff(
            lambda: self._fetch_raw_results(batch_id),
            max_attempts=3,
            initial_delay=2.0
        )

        # Optionally write to file
        if output_directory:
            result_file_path = self._write_results_to_file(batch_id, raw_results, output_directory)
            # Parse from file
            return self._read_jsonl_file(result_file_path)
        else:
            # Parse from memory
            batch_results = []
            lines = raw_results.decode('utf-8').strip().split('\n')
            for line_num, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        raw_result = json.loads(line)
                        batch_result = self.parse_provider_response(raw_result)
                        batch_results.append(batch_result)
                    except json.JSONDecodeError as e:
                        logger.error(f'JSON parsing error on line {line_num}: {e}')
                        batch_results.append(BatchResult(
                            custom_id=f'error_line_{line_num}',
                            content=None,
                            success=False,
                            error=f'JSON parsing error: {e}',
                            metadata={'line_number': line_num, 'raw_line': line[:500]}
                        ))
            return batch_results

    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """
        Transform provider-specific response format to standardized BatchResult (Template Method).

        This template method provides the common workflow:
        1. Extract custom_id
        2. Check for errors first
        3. Extract content, metadata, and usage if successful

        Providers implement:
        - _extract_custom_id() - Get request ID from response
        - _extract_error_from_response() - Check for error conditions
        - _extract_content_from_response() - Get main response content
        - _extract_metadata_from_response() - Get provider metadata
        - _extract_usage_from_response() - Get token usage info

        Args:
            raw_response: Provider-specific response object/dict

        Returns:
            Standardized BatchResult object

        Example:
            OpenAI returns: {"custom_id": "123", "response": {"body": {"choices": [...]}}}
            Another provider returns: {"id": "123", "result": {"data": "..."}}
            Both get transformed to: BatchResult(custom_id="123", content={...}, success=True)
        """
        # Extract custom_id
        custom_id = self._extract_custom_id(raw_response)

        # Check for errors first
        error = self._extract_error_from_response(raw_response)
        if error:
            return BatchResult(
                custom_id=custom_id,
                content=None,
                success=False,
                error=error
            )

        # Extract successful response data
        content = self._extract_content_from_response(raw_response)

        # Parse JSON content if it's a string
        if isinstance(content, str):
            content = self._parse_json_content(content)

        metadata = self._extract_metadata_from_response(raw_response)
        usage = self._extract_usage_from_response(raw_response)

        return BatchResult(
            custom_id=custom_id,
            content=content,
            success=True,
            error=None,
            metadata=metadata,
            usage=usage
        )

    def _extract_custom_id(self, raw_response: Any) -> str:
        """
        Extract custom_id from response (Helper Method).

        Provides default implementation using _get_attribute_or_key helper.
        Providers can override if needed.

        Args:
            raw_response: Provider-specific response

        Returns:
            Custom ID string, or 'unknown' if not found
        """
        return self._get_attribute_or_key(raw_response, 'custom_id', 'unknown')

    @abstractmethod
    def _extract_error_from_response(self, raw_response: Any) -> Optional[str]:
        """
        Extract error message from response.

        Subclasses MUST implement this to check for error conditions.

        Args:
            raw_response: Provider-specific response

        Returns:
            Error message string if error exists, None otherwise
        """
        pass

    @abstractmethod
    def _extract_content_from_response(self, raw_response: Any) -> Any:
        """
        Extract main content from successful response.

        Subclasses MUST implement this to get the actual response content.

        Args:
            raw_response: Provider-specific response

        Returns:
            Content (can be dict, str, list, etc.)
        """
        pass

    @abstractmethod
    def _extract_metadata_from_response(self, raw_response: Any) -> Dict[str, Any]:
        """
        Extract metadata from response.

        Subclasses MUST implement this to get provider-specific metadata
        (model name, finish_reason, etc.).

        Args:
            raw_response: Provider-specific response

        Returns:
            Metadata dictionary
        """
        pass

    @abstractmethod
    def _extract_usage_from_response(self, raw_response: Any) -> Optional[Dict[str, Any]]:
        """
        Extract usage information from response.

        Subclasses MUST implement this to get token usage data.

        Args:
            raw_response: Provider-specific response

        Returns:
            Usage dictionary with token counts, or None if not available
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
        Validate that the agent configuration is compatible with this provider (Template Method).

        This template method provides common validation for all providers.
        Providers can implement _validate_provider_specific_config() for additional checks.

        Model validation is delegated to the API provider itself, which will
        return appropriate errors for invalid model names.

        Args:
            agent_config: Agent configuration to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not agent_config:
            return (False, 'agent_config is required')

        return self._validate_provider_specific_config(agent_config)

    def _validate_provider_specific_config(self, agent_config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Perform provider-specific configuration validation.

        Subclasses MAY override this for additional provider-specific validation.
        Default implementation accepts all configurations.

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
        from agent_actions.utilities.path_utils import ensure_directory_exists
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
            from agent_actions.errors import VendorAPIError  # New modular pattern!
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

    def _parse_json_content(self, content_str: str) -> Any:
        """
        Parse JSON string, return as-is if parsing fails.

        This helper eliminates duplicated JSON parsing logic across providers.

        Args:
            content_str: String to parse as JSON

        Returns:
            Parsed JSON object, or original string if parsing fails
        """
        if not isinstance(content_str, str):
            return content_str

        try:
            return json.loads(content_str)
        except json.JSONDecodeError:
            return content_str

    def _retry_with_backoff(
        self,
        operation: callable,
        max_attempts: int = 3,
        initial_delay: float = 1.0
    ) -> Any:
        """
        Retry operation with exponential backoff.

        This helper eliminates duplicated retry logic in OpenAI and Gemini providers.

        Args:
            operation: Callable to execute (should take no arguments)
            max_attempts: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay in seconds (default: 1.0)

        Returns:
            Result from successful operation execution

        Raises:
            Exception from last failed attempt if all retries exhausted
        """
        import time
        import logging
        logger = logging.getLogger(__name__)

        for attempt in range(max_attempts):
            try:
                return operation()
            except Exception as e:
                if attempt == max_attempts - 1:
                    # Log final failure after all retries exhausted
                    logger.error(
                        "All retry attempts exhausted",
                        extra={
                            'operation': 'retry_exhausted',
                            'total_attempts': max_attempts,
                            'final_error': str(e),
                            'error_type': type(e).__name__
                        }
                    )
                    raise

                delay = initial_delay * (2 ** attempt)

                # Log retry attempt with configuration and wait time
                logger.warning(
                    f"Retry attempt {attempt + 1}/{max_attempts} after failure",
                    extra={
                        'operation': 'retry_attempt',
                        'attempt': attempt + 1,
                        'max_attempts': max_attempts,
                        'wait_time': delay,
                        'initial_delay': initial_delay,
                        'backoff_base': 2,
                        'error': str(e),
                        'error_type': type(e).__name__
                    }
                )
                time.sleep(delay)

    def _get_attribute_or_key(self, obj: Any, key: str, default: Any = None) -> Any:
        """
        Get value from object attribute or dict key.

        This helper eliminates repeated hasattr/isinstance checks,
        particularly in Anthropic provider's parse_provider_response().

        Args:
            obj: Object to extract value from (can be object or dict)
            key: Attribute name or dict key
            default: Default value if key not found

        Returns:
            Value from obj.key or obj[key], or default if not found
        """
        if hasattr(obj, key):
            return getattr(obj, key)
        elif isinstance(obj, dict):
            return obj.get(key, default)
        return default

    def _write_results_to_file(self, batch_id: str, raw_results: bytes, output_directory: Optional[str] = None) -> Path:
        """
        Write raw results to JSONL file.

        This helper eliminates duplicated file writing logic across providers.

        Args:
            batch_id: Batch job ID (used for filename)
            raw_results: Raw results as bytes
            output_directory: Optional directory for results

        Returns:
            Path to written file
        """
        batch_dir = self._get_batch_directory(output_directory)
        result_file_name = self._get_result_file_name(batch_id)
        result_file_path = batch_dir / result_file_name

        with open(result_file_path, 'wb') as f:
            f.write(raw_results)

        print(f'Saved raw results to: {result_file_path}')
        return result_file_path

    @abstractmethod
    def _get_result_file_name(self, batch_id: str) -> str:
        """
        Get the result file name for a batch.

        Subclasses MUST implement this to specify their result file naming convention.

        Args:
            batch_id: Batch job ID

        Returns:
            File name for results (e.g., "batch_123_results.jsonl")
        """
        pass

    @abstractmethod
    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """
        Fetch raw results from provider API.

        Subclasses MUST implement this to call their provider's results API.

        Args:
            batch_id: Provider-specific batch job ID

        Returns:
            Raw results as bytes
        """
        pass

    @abstractmethod
    def _prepare_batch_input_file(self, tasks: List[Dict[str, Any]], batch_dir: Path, batch_name: str) -> Path:
        """
        Prepare batch input file.

        Subclasses MUST implement this to write tasks to a file in their provider's format.

        Args:
            tasks: List of provider-specific task dictionaries
            batch_dir: Directory to write file to
            batch_name: Base name for the batch

        Returns:
            Path to created input file
        """
        pass

    @abstractmethod
    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> Tuple[str, str]:
        """
        Submit batch to provider API.

        Subclasses MUST implement this to call their provider's batch submission API.

        Args:
            input_file: Path to prepared input file
            batch_name: Name for the batch job

        Returns:
            Tuple of (batch_id, initial_status)
        """
        pass