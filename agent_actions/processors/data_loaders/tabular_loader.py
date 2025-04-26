"""Tabular content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple
import csv

from agent_actions.processors.data_loaders.base_loader import BaseLoader

# Configure logger
logger = logging.getLogger(__name__)


class TabularLoader(BaseLoader):
    """Loader for tabular content like CSV and Excel."""
    
    def __init__(self, agent_config: Dict[str, Any], agent_name: str, prompt_processor):
        """Initialize with agent configuration, name, and prompt processor.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
            prompt_processor: Processor for handling prompts
        """
        super().__init__(agent_config, agent_name)
        self.prompt_processor = prompt_processor
    
    def process(self, content: Any, file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load and process tabular content from a CSV/TSV file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the CSV/TSV file.

        Returns:
            Tuple containing transformed response and source text.
        """
        data_chunk = []
        src_text = []

        try:
            if file_path:
                content_str = self.load_file(file_path)
            elif content:
                content_str = content
            else:
                raise ValueError("Either file_path or content must be provided for tabular processing.")

            rows = list(csv.DictReader(content_str.splitlines()))

            for row in rows:
                dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(row)
                data_chunk.extend(dynamic_agent)
                src_text.extend(src_collection)
        except Exception as e:
            self.handle_processing_error(e, "processing tabular file")

        return data_chunk, src_text

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".csv", ".tsv"]