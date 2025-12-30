"""JSON content loader implementation."""

# pylint: disable=duplicate-code
# Similar loader pattern is intentional across different file type loaders
import json
import logging
from typing import Any, Dict, List, Optional, Union

from agent_actions.errors import DataParseError, FileLoadError, ValidationError
from agent_actions.input_loading.base_base_loader import BaseLoader

logger = logging.getLogger(__name__)


class JsonLoader(BaseLoader[Union[Dict[str, Any], List[Dict[str, Any]]]]):
    """Loader for JSON content."""

    def process(
        self, content: Any, file_path: Optional[str] = None
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Load and return raw JSON content from a file or memory.

        Args:
            content: JSON content to process if file_path is not provided.
            file_path: Path to the JSON file.

        Returns:
            Parsed JSON object (list or dictionary).
        """
        try:
            if file_path:
                content_str = self.load_file(file_path)
                return json.loads(content_str)
            if content:
                return json.loads(content)

            error_context = {
                "agent_name": self.agent_name,
                "loader_type": "json",
                "failed_fields": ["file_path", "content"],
                "expected": "At least one of file_path or content must be provided",
                "actual_values": {"file_path": file_path, "content": content},
                "suggestion": (
                    "Provide either the file_path parameter (path to JSON file) "
                    "or the content parameter (JSON string) for JSON data processing."
                ),
            }
            error = ValidationError(
                "Either file_path or content must be provided", context=error_context
            )
            self.handle_validation_error(error, "JSON input", file_path=file_path)
            raise error
        except json.JSONDecodeError as e:
            operation = f"Parsing JSON from {file_path or 'content string'}"
            self.handle_processing_error(
                e,
                operation,
                DataParseError,
                file_path=file_path,
                line_number=e.lineno if hasattr(e, "lineno") else None,
                column_number=e.colno if hasattr(e, "colno") else None,
            )
            raise
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(
                e, "Processing JSON content", DataParseError, file_path=file_path
            )
            raise

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in [".json"]
