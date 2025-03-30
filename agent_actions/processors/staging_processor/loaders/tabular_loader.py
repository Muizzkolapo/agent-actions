"""Tabular content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from agent_actions.processors.staging_processor.loaders.base_loader import BaseLoader

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
    
    def process(self, 
               content: List[Dict[str, Any]],
               file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process tabular content.
        
        Args:
            content: Tabular content as list of dictionaries (rows)
            file_path: Not used for tabular processing, included for API consistency
            
        Returns:
            Tuple containing transformed response and source text
        """
        data_chunk = []
        src_text = []
        
        for row in content:
            try:
                dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(row)
                data_chunk.extend(dynamic_agent)
                src_text.extend(src_collection)
            except Exception as e:
                self.handle_processing_error(e, f"processing tabular row: {str(row)[:50]}...")
                # Continue processing other rows
                
        return data_chunk, src_text