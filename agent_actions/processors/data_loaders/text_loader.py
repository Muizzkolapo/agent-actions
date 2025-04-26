"""Text content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from agent_actions.processors.data_loaders.base_loader import BaseLoader

# Configure logger
logger = logging.getLogger(__name__)


class TextLoader(BaseLoader):
    """Loader for text-based content like TXT, MD, PDF, DOCX, and HTML."""
    
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
        """Load and process text content from a file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the text file.

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
                raise ValueError("Either file_path or content must be provided for text processing.")

            dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(content_str)
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)

        except Exception as e:
            self.handle_processing_error(e, "processing text input")

        return data_chunk, src_text

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".txt", ".md", ".html"]