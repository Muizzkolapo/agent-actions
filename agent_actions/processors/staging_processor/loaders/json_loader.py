"""JSON content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from agent_actions.handlers.file_handler import FileHandler

from agent_actions.processors.staging_processor.loaders.base_loader import BaseLoader

# Configure logger
logger = logging.getLogger(__name__)


class JsonLoader(BaseLoader):
    """Loader for JSON content."""
    
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
               content: Union[List[Dict[str, Any]], Dict[str, Any]], 
               file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process JSON content.
        
        Args:
            content: JSON content
            file_path: Path to the file
            
        Returns:
            Tuple containing transformed response and source text
        """
        data_chunk = []
        src_text = []
        src_legacy_path = FileHandler.get_file_info(file_path) if file_path else None
        
        try:
            if isinstance(content, list):
                self._process_json_list(content, src_legacy_path, data_chunk, src_text)
            elif isinstance(content, dict):
                self._process_json_dict(content, src_legacy_path, data_chunk, src_text)
        except Exception as e:
            self.handle_processing_error(e, "processing JSON content")
            
        return data_chunk, src_text
        
    def _process_json_list(self, 
                          content: List[Dict[str, Any]], 
                          src_legacy_path: Optional[str], 
                          data_chunk: List[Dict[str, Any]], 
                          src_text: List[Dict[str, Any]]) -> None:
        """Process a list of JSON objects.
        
        Args:
            content: List of JSON objects
            src_legacy_path: Path to the source file
            data_chunk: List to append data chunks to
            src_text: List to append source text to
        """
        for obj in content:
            try:
                dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(
                    context_data=obj,
                    source_path=src_legacy_path
                )
                data_chunk.extend(dynamic_agent)
                src_text.extend(src_collection)
            except Exception as e:
                self.handle_processing_error(e, f"processing JSON list object: {str(obj)[:50]}...")
                
    def _process_json_dict(self, 
                         content: Dict[str, Any], 
                         src_legacy_path: Optional[str], 
                         data_chunk: List[Dict[str, Any]], 
                         src_text: List[Dict[str, Any]]) -> None:
        """Process a JSON dictionary.
        
        Args:
            content: JSON dictionary
            src_legacy_path: Path to the source file
            data_chunk: List to append data chunks to
            src_text: List to append source text to
        """
        for key, value in content.items():
            if isinstance(value, list):
                for obj in value:
                    try:
                        dynamic_agent, src_collection = self.prompt_processor.staging_dynamic_creator(
                            context_data=obj,
                            source_path=src_legacy_path
                        )
                        data_chunk.extend(dynamic_agent)
                        src_text.extend(src_collection)
                    except Exception as e:
                        self.handle_processing_error(e, f"processing JSON dict list item: {str(obj)[:50]}...")
            else:
                try:
                    generated_content, src_collection = self.prompt_processor.staging_dynamic_creator(
                        context_data=content,
                        source_path=src_legacy_path
                    )
                    data_chunk.extend(generated_content)
                    src_text.extend(src_collection)
                except Exception as e:
                    self.handle_processing_error(e, f"processing JSON dict: {str(content)[:50]}...")