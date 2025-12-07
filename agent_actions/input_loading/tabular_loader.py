"""Tabular content loader implementation."""
import logging
from typing import Any, Dict, List, Optional
from agent_actions.response_processing.config_types import AgentEntryDict
import csv
from agent_actions.input_loading.base_base_loader import BaseLoader
from agent_actions.errors import AgentActionsException  # New modular pattern!
logger = logging.getLogger(__name__)

class TabularLoader(BaseLoader[List[Dict[str, Any]]]):
    """Loader for tabular content like CSV and Excel."""

    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)

    def process(self, content: Any, file_path: Optional[str]=None) -> List[Dict[str, Any]]:
        """Load and return tabular content from a CSV/TSV file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the CSV/TSV file.

        Returns:
            Parsed list of dictionaries representing the rows.
        """
        try:
            if file_path:
                content_str = self.load_file(file_path)
            elif content:
                content_str = content
            else:
                from agent_actions.errors import ValidationError  # New modular pattern!
                raise ValidationError(
                    'Either file_path or content must be provided for tabular processing',
                    context={
                        'agent_name': self.agent_name,
                        'loader_type': 'tabular',
                        'failed_fields': ['file_path', 'content'],
                        'expected': 'At least one of file_path or content must be provided',
                        'actual_values': {'file_path': file_path, 'content': content},
                        'suggestion': 'Provide either the file_path parameter (path to tabular file) or the content parameter (string content) for tabular data processing.'
                    }
                )
            rows = list(csv.DictReader(content_str.splitlines()))
            return rows
        except csv.Error as e:
            self.handle_processing_error(e, f"parsing CSV from {file_path or 'content string'}")
            raise AgentActionsException('Invalid CSV data', context={'agent_name': self.agent_name, 'file_path': file_path, 'loader_type': 'tabular'}, cause=e)
        except IOError as e:
            self.handle_processing_error(e, f'reading tabular file {file_path}')
            raise AgentActionsException('Could not read tabular file', context={'agent_name': self.agent_name, 'file_path': file_path, 'loader_type': 'tabular'}, cause=e)
        except Exception as e:
            self.handle_processing_error(e, 'processing tabular file')
            raise AgentActionsException('Failed to process tabular data', context={'agent_name': self.agent_name, 'file_path': file_path, 'loader_type': 'tabular'}, cause=e)

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in ['.csv', '.tsv']