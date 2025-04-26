"""JSON content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from agent_actions.handlers.file_handler import FileHandler

from agent_actions.processors.data_loaders.base_loader import BaseLoader
import json

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
        


    def process(self, content: Any, file_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load and process JSON content from a file.

        Args:
            content: (Ignored)
            file_path: Path to the JSON file.

        Returns:
            Tuple containing transformed response and source text.
        """
        data_chunk = []
        src_text = []

        try:
            content_str = self.load_file(file_path)
            content_json = json.loads(content_str)
            src_legacy_path = FileHandler.get_file_info(file_path)

            if isinstance(content_json, list):
                self._process_json_list(content_json, src_legacy_path, data_chunk, src_text)
            elif isinstance(content_json, dict):
                self._process_json_dict(content_json, src_legacy_path, data_chunk, src_text)
            else:
                raise ValueError("Unsupported JSON structure.")
        except Exception as e:
            self.handle_processing_error(e, "processing JSON file")

        return data_chunk, src_text

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".json"]
        
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