"""JSON content loader implementation."""
import json
import logging
from typing import Any, Dict, List, Optional, Union
from agent_actions.response_processing.config_types import AgentEntryDict
from agent_actions.input_loading.base_base_loader import BaseLoader
from agent_actions.shared.exceptions import DataParseError, FileLoadError
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

    def process(self, content: Any, file_path: Optional[str]=None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
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
                parsed_data: Union[Dict[str, Any], List[Dict[str, Any]]] = json.loads(content_str)
                return parsed_data
            elif content:
                parsed_data = json.loads(content)
                return parsed_data
            else:
                from agent_actions.shared.exceptions import ValidationError
                error = ValidationError(
                    'Either file_path or content must be provided',
                    context={
                        'agent_name': self.agent_name,
                        'loader_type': 'json',
                        'failed_fields': ['file_path', 'content'],
                        'expected': 'At least one of file_path or content must be provided',
                        'actual_values': {'file_path': file_path, 'content': content},
                        'suggestion': 'Provide either the file_path parameter (path to JSON file) or the content parameter (JSON string) for JSON data processing.'
                    }
                )
                self.handle_validation_error(error, 'JSON input', file_path=file_path)
                raise error
        except json.JSONDecodeError as e:
            self.handle_processing_error(e, f"Parsing JSON from {file_path or 'content string'}", DataParseError, file_path=file_path, line_number=e.lineno if hasattr(e, 'lineno') else None, column_number=e.colno if hasattr(e, 'colno') else None)
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(e, 'Processing JSON content', DataParseError, file_path=file_path)
            raise

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in ['.json']