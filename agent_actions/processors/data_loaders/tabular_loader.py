"""Tabular content loader implementation."""
import logging
from typing import Any, Dict, List, Optional
import csv

from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.cli.exceptions import AgentActionsError # Or a more specific DataLoaderError

# Configure logger
logger = logging.getLogger(__name__)


class TabularLoader(BaseLoader):
    """Loader for tabular content like CSV and Excel."""
    
    def __init__(self, agent_config: Dict[str, Any], agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)
    
    def process(self, content: Any, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
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
                raise ValueError("Either file_path or content must be provided for tabular processing.")

            rows = list(csv.DictReader(content_str.splitlines()))
            return rows
        except csv.Error as e:
            self.handle_processing_error(e, f"parsing CSV from {file_path or 'content string'}")
            raise AgentActionsError(f"Invalid CSV data in {file_path or 'content string'}: {e}") from e
        except IOError as e: # From self.load_file
            self.handle_processing_error(e, f"reading tabular file {file_path}")
            raise AgentActionsError(f"Could not read tabular file {file_path}: {e}") from e
        except Exception as e:
            self.handle_processing_error(e, "processing tabular file")
            raise AgentActionsError(f"Failed to process tabular data from {file_path or 'content string'}: {e}") from e

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".csv", ".tsv"]