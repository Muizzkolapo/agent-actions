"""XML content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from agent_actions.processors.staging_processor.loaders.base_loader import BaseLoader

# Configure logger
logger = logging.getLogger(__name__)


class XmlLoader(BaseLoader):
    """Loader for XML content."""
    
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
               content: Tuple[Any, Any],
               file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Process XML content.
        
        Args:
            content: XML content tuple (typically document and root element)
            file_path: Not used for XML processing, included for API consistency
            
        Returns:
            Tuple containing transformed response and source text
        """
        data_chunk = []
        src_text = []
        
        try:
            _, root = content
            for element in root.findall('.//*'):
                if list(element):  # Only process elements that have children
                    element_dict = self.process_xml_element(element)
                    chunk_output, src_collection = self.prompt_processor.staging_dynamic_creator(element_dict)
                    data_chunk.extend(chunk_output)
                    src_text.extend(src_collection)
        except Exception as e:
            self.handle_processing_error(e, "processing XML content")
            
        return data_chunk, src_text
        
    def process_xml_element(self, element: Any) -> Dict[str, Any]:
        """Process an XML element into a dictionary.
        
        Args:
            element: XML element
            
        Returns:
            Dictionary representation of the XML element
        """
        try:
            result = {
                'tag': element.tag,
                'attributes': element.attrib,
                'text': element.text.strip() if element.text else '',
                'children': []
            }
            
            for child in element:
                result['children'].append(self.process_xml_element(child))
                
            return result
        except Exception as e:
            self.handle_processing_error(e, f"processing XML element: {element.tag}")
            raise