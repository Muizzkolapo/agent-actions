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
from datetime import datetime


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
    content: Any  # The actual result content (could be dict, str, etc.)
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
    def prepare_tasks(self, 
                     data: List[Dict[str, Any]], 
                     agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    def format_task_for_provider(self, 
                                batch_task: BatchTask,
                                schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    def submit_batch(self, 
                    tasks: List[Dict[str, Any]], 
                    batch_name: str,
                    output_directory: Optional[str] = None) -> str:
        """
        Submit a batch job to the provider.
        
        Args:
            tasks: List of provider-specific tasks from prepare_tasks()
            batch_name: Name for the batch job
            output_directory: Optional directory for storing batch-related files
            
        Returns:
            Batch job ID from the provider
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
    def retrieve_results(self, 
                        batch_id: str, 
                        output_directory: Optional[str] = None) -> List[BatchResult]:
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
        # Default implementation - returns schema as-is
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
        return True, None