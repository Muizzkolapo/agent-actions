"""JSON content loader implementation."""
import json
import logging
from typing import Any, Dict, List, Optional, Union

from agent_actions.models.config_types import AgentEntryDict
from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.processors.exceptions import DataParseError, FileLoadError

# Configure logger
logger = logging.getLogger(__name__)


class JsonLoader(BaseLoader[Union[Dict[str, Any], List[Dict[str, Any]]]]):
    """Loader for JSON content."""
    
    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
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
                self.handle_validation_error(
                    ValueError("Either file_path or content must be provided"),
                    "JSON input",
                    file_path=file_path
                )
        except json.JSONDecodeError as e:
            self.handle_processing_error(
                e,
                f"Parsing JSON from {file_path or 'content string'}",
                DataParseError,
                file_path=file_path,
                line_number=e.lineno if hasattr(e, 'lineno') else None,
                column_number=e.colno if hasattr(e, 'colno') else None
            )
        except FileLoadError:
            # Already handled by base loader
            raise
        except Exception as e:
            self.handle_processing_error(
                e,
                "Processing JSON content",
                DataParseError,
                file_path=file_path
            )

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".json"]