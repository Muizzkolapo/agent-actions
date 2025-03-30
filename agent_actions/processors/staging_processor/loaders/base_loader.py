"""Base class for content loaders."""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union

# Configure logger
logger = logging.getLogger(__name__)


class BaseLoader(ABC):
    """Abstract base class for all content loaders."""
    
    def __init__(self, agent_config: Dict[str, Any], agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        
    @abstractmethod
    def process(self, 
               content: Any,
               file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process content specific to the loader implementation.
        
        Args:
            content: Content to process
            file_path: Path to the file
            
        Returns:
            Tuple containing transformed response and source text
        """
        pass
        
    def handle_processing_error(self, 
                               error: Exception, 
                               error_context: str) -> None:
        """Handle processing errors consistently.
        
        Args:
            error: The exception that occurred
            error_context: Context about where the error occurred
        """
        logger.error(f"Error in {error_context}: {str(error)}")
        # In a production system, we might want to notify monitoring systems or log to a central service