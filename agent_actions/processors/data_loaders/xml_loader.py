"""XML content loader implementation."""
import logging
from typing import Any, Dict, Optional
from agent_actions.models.config_types import AgentEntryDict
import xml.etree.ElementTree as ET

from agent_actions.processors.data_loaders.base_loader import BaseLoader
from agent_actions.cli.exceptions import AgentActionsError # Or a more specific DataLoaderError

# Configure logger
logger = logging.getLogger(__name__)


class XmlLoader(BaseLoader[ET.Element]):
    """Loader for XML content."""
    
    def __init__(self, agent_config: AgentEntryDict, agent_name: str):
        """Initialize with agent configuration and name.
        
        Args:
            agent_config: Agent configuration
            agent_name: Name of the agent
        """
        super().__init__(agent_config, agent_name)
    
    def process(self, content: Any, file_path: Optional[str] = None) -> ET.Element:
        """Load and return XML root element from a file or in-memory content.

        Args:
            content: Content to process if file_path is not provided.
            file_path: Path to the XML file.

        Returns:
            Parsed XML ElementTree root element.
        """
        try:
            if file_path:
                content_str = self.load_file(file_path)
            elif content:
                content_str = content
            else:
                raise ValueError("Either file_path or content must be provided for XML processing.")

            root = ET.fromstring(content_str)
            return root
        except ET.ParseError as e:
            self.handle_processing_error(e, f"parsing XML from {file_path or 'content string'}")
            raise AgentActionsError(f"Invalid XML data in {file_path or 'content string'}: {e}") from e
        except IOError as e: # From self.load_file
            self.handle_processing_error(e, f"reading XML file {file_path}")
            raise AgentActionsError(f"Could not read XML file {file_path}: {e}") from e
        except Exception as e:
            self.handle_processing_error(e, "processing XML input")
            raise AgentActionsError(f"Failed to process XML input from {file_path or 'content string'}: {e}") from e
        
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