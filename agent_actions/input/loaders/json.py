"""JSON content loader implementation."""

# Similar loader pattern is intentional across different file type loaders
import json
import logging
from typing import Any

from agent_actions.errors import FileLoadError, ValidationError
from agent_actions.input.loaders.base import BaseLoader

logger = logging.getLogger(__name__)


class JsonLoader(BaseLoader[dict[str, Any] | list[dict[str, Any]]]):
    """Loader for JSON content."""

    def process(
        self, content: Any, file_path: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Load and return raw JSON content from a file or memory."""
        # If content is already parsed (from FileReader._read_json), return directly
        if isinstance(content, (dict, list)):
            return content
        try:
            if file_path:
                content_str = self.load_file(file_path)
                result: dict[str, Any] | list[dict[str, Any]] = json.loads(content_str)
                return result
            if content:
                result = json.loads(content)
                return result

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
                ValidationError,
                file_path=file_path,
                line_number=e.lineno if hasattr(e, "lineno") else None,
                column_number=e.colno if hasattr(e, "colno") else None,
            )
            raise
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(
                e, "Processing JSON content", ValidationError, file_path=file_path
            )
            raise

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in {".json"}
