"""JSON content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from agent_actions.handlers.file_handler import FileHandler

from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.cli.exceptions import AgentActionsError # Or a more specific DataLoaderError
import json

# Configure logger
logger = logging.getLogger(__name__)


class JsonLoader(BaseLoader):
    """Loader for JSON content."""
    
    def __init__(self, agent_config: Dict[str, Any], agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)
        

    def process(self, content: Any, file_path: Optional[str] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Load and return raw JSON content from a file or memory.

        Args:
            content: JSON content to process if file_path is not provided.
            file_path: Path to the JSON file.

        Returns:
            Parsed JSON object (list or dictionary).
        """
        try:
            if file_path:
                content_str = self.load_file(file_path)
                return json.loads(content_str)
            elif content:
                return json.loads(content)
            else:
                raise ValueError("Either file_path or content must be provided for JSON processing.")
        except json.JSONDecodeError as e:
            self.handle_processing_error(e, f"decoding JSON from {file_path or 'content string'}")
            raise AgentActionsError(f"Invalid JSON data in {file_path or 'content string'}: {e}") from e
        except IOError as e: # From self.load_file
            self.handle_processing_error(e, f"reading JSON file {file_path}")
            raise AgentActionsError(f"Could not read JSON file {file_path}: {e}") from e
        except Exception as e:
            self.handle_processing_error(e, "processing JSON file")
            raise AgentActionsError(f"Failed to process JSON from {file_path or 'content string'}: {e}") from e

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".json"]