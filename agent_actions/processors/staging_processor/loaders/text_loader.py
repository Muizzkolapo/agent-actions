"""Text content loader implementation."""
import logging
from typing import Any, Dict, List, Tuple

from agent_actions.processors.staging_processor.loaders.base_loader import BaseLoader

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
        
    def process(self, 
               chunks: List[str],
               file_path=None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process text chunks.
        
        Args:
            chunks: List of text chunks
            file_path: Not used for text processing, included for API consistency
            
        Returns:
            Tuple containing transformed response and source text
        """
        data_chunk = []
        src_text = []
        
        for context_data in chunks:
            try:
                dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(context_data)
                data_chunk.extend(dynamic_agent)
                src_text.extend(src_collection)
            except Exception as e:
                self.handle_processing_error(e, f"processing text chunk: {context_data[:50]}...")
                # Continue processing other chunks
                
        return data_chunk, src_text