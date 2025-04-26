"""XML content loader implementation."""
import logging
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from agent_actions.processors.data_loaders.base_loader import BaseLoader

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
        
    def process(self, content: Any, file_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load and process XML content from a file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the XML file.

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
                raise ValueError("Either file_path or content must be provided for XML processing.")

            root = ET.fromstring(content_str)

            for element in root.findall('.//*'):
                if list(element):  # Only process elements that have children
                    element_dict = self.process_xml_element(element)
                    chunk_output, src_collection = self.prompt_processor.staging_dynamic_creator(element_dict)
                    data_chunk.extend(chunk_output)
                    src_text.extend(src_collection)
        except Exception as e:
            self.handle_processing_error(e, "processing XML input")

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

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".xml"]