"""Text content loader implementation."""
import logging
from typing import Any, Optional
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.input_loading.base_base_loader import BaseLoader
from agent_actions.errors import FileLoadError  # New modular pattern!
logger = logging.getLogger(__name__)

class TextLoader(BaseLoader[str]):
    """Loader for text-based content like TXT, MD, PDF, DOCX, and HTML."""

    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)

    def process(self, content: Any, file_path: Optional[str]=None) -> str:
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
                return str(content)
            else:
                self.handle_validation_error(ValueError('Either file_path or content must be provided'), 'text input', file_path=file_path)
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(e, 'Processing text content', file_path=file_path)

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in ['.txt', '.md', '.html']