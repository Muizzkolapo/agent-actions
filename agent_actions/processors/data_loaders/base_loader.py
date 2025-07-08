"""Base class for content loaders."""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar, Generic
from agent_actions.models.config_types import AgentEntryDict

__version__ = "0.1.0"

# Configure logger
logger = logging.getLogger(__name__)


T = TypeVar("T")


class BaseLoader(ABC, Generic[T]):
    """Abstract base class for all content loaders."""
    
    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.logger = logging.getLogger(__name__)

    def load_file(self, file_path: str) -> str:
        """Safely load a file's content."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            self.handle_processing_error(e, f"Loading file: {file_path}")
            raise
        
    @abstractmethod
    def process(
        self,
        content: Any,
        file_path: Optional[str] = None
    ) -> T:
        """Load and parse content from a file or in-memory input.

        Args:
            content: Raw content provided directly (optional if file_path is provided).
            file_path: Path to the file to load content from.

        Returns:
            Parsed content such as a string, dictionary, or list depending on loader type.
        """
        pass

    @abstractmethod
    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if this loader can handle the given file extension."""
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