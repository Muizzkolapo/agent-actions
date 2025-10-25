"""XML content loader implementation."""
import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from agent_actions.core.parser.config_types import AgentEntryDict
from agent_actions.agents.base.base_loader import BaseLoader
from agent_actions.core.exceptions import DataParseError, FileLoadError

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
                self.handle_validation_error(
                    ValueError("Either file_path or content must be provided"),
                    "XML input",
                    file_path=file_path
                )

            root = ET.fromstring(content_str)
            return root
        except ET.ParseError as e:
            # Extract line/column info if available
            position_info = {}
            if hasattr(e, 'position'):
                position_info['line_number'] = e.position[0]
                position_info['column_number'] = e.position[1]
            
            self.handle_processing_error(
                e,
                f"Parsing XML from {file_path or 'content string'}",
                DataParseError,
                file_path=file_path,
                **position_info
            )
        except FileLoadError:
            # Already handled by base loader
            raise
        except Exception as e:
            self.handle_processing_error(
                e,
                "Processing XML content",
                DataParseError,
                file_path=file_path
            )
        
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
            self.handle_transformation_error(
                e,
                "XML element",
                "dictionary",
                element_tag=element.tag if hasattr(element, 'tag') else 'unknown'
            )

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".xml"]