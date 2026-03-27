"""XML content loader implementation."""

# Similar loader pattern is intentional across different file type loaders
import logging

# ET is used for type annotations (ET.Element) and exception handling
# (ET.ParseError).  DefusedET handles all actual parsing.
import xml.etree.ElementTree as ET
from typing import Any

import defusedxml.ElementTree as DefusedET  # type: ignore[import-untyped]

from agent_actions.errors import FileLoadError, ValidationError
from agent_actions.input.loaders.base import BaseLoader

logger = logging.getLogger(__name__)


class XmlLoader(BaseLoader[ET.Element]):
    """Loader for XML content."""

    def process(self, content: Any, file_path: str | None = None) -> ET.Element:
        """Load and return XML root element from a file or in-memory content."""
        try:
            if file_path:
                content_str = self.load_file(file_path)
            elif content:
                content_str = content
            else:
                error = ValueError("Either file_path or content must be provided")
                self.handle_validation_error(error, "XML input", file_path=file_path)
                raise error
            root: ET.Element = DefusedET.fromstring(content_str)
            return root
        except ET.ParseError as e:
            position_info: dict[str, Any] = {}
            if hasattr(e, "position"):
                position_info["line_number"] = e.position[0]
                position_info["column_number"] = e.position[1]
            operation = f"Parsing XML from {file_path or 'content string'}"
            self.handle_processing_error(
                e, operation, ValidationError, file_path=file_path, **position_info
            )
            raise
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(
                e, "Processing XML content", ValidationError, file_path=file_path
            )
            raise

    def process_xml_element(self, element: Any) -> dict[str, Any]:
        """Process an XML element into a dictionary."""
        try:
            result = {
                "tag": element.tag,
                "attributes": element.attrib,
                "text": element.text.strip() if element.text else "",
                "children": [],
            }
            for child in element:
                result["children"].append(self.process_xml_element(child))
            return result
        except Exception as e:
            element_tag = element.tag if hasattr(element, "tag") else "unknown"
            self.handle_transformation_error(
                e, "XML element", "dictionary", element_tag=element_tag
            )
            raise

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in {".xml"}
