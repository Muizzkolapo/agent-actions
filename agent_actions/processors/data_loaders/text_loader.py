"""Text content loader implementation."""
import logging
from typing import Any, Dict, Optional

from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.cli.exceptions import AgentActionsError # Or a more specific DataLoaderError

# Configure logger
logger = logging.getLogger(__name__)


class TextLoader(BaseLoader):
    """Loader for text-based content like TXT, MD, PDF, DOCX, and HTML."""
    
    def __init__(self, agent_config: Dict[str, Any], agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)
        
    def process(self, content: Any, file_path: Optional[str] = None) -> str:
        """Load and return text content from a file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the text file.

        Returns:
            Loaded text content as a string.
        """
        try:
            if file_path:
                return self.load_file(file_path)
            elif content:
                return content
            else:
                raise ValueError("Either file_path or content must be provided for text processing.")
        except IOError as e: # From self.load_file
            self.handle_processing_error(e, f"reading text file {file_path}")
            raise AgentActionsError(f"Could not read text file {file_path}: {e}") from e
        except Exception as e:
            self.handle_processing_error(e, "processing text input")
            raise AgentActionsError(f"Failed to process text input from {file_path or 'content string'}: {e}") from e

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".txt", ".md", ".html"]