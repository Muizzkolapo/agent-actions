"""Tabular content loader implementation."""

# Similar loader pattern is intentional across different file type loaders
import csv
import logging
from typing import Any

from agent_actions.errors import AgentActionsError, ValidationError
from agent_actions.input.loaders.base import BaseLoader

logger = logging.getLogger(__name__)


class TabularLoader(BaseLoader[list[dict[str, Any]]]):
    """Loader for tabular content like CSV and Excel."""

    def process(self, content: Any, file_path: str | None = None) -> list[dict[str, Any]]:
        """Load and return tabular content from a CSV/TSV file or in-memory content."""
        try:
            if file_path:
                content_str = self.load_file(file_path)
            elif content:
                content_str = content
            else:
                error_context: dict[str, Any] = {
                    "agent_name": self.agent_name,
                    "loader_type": "tabular",
                    "failed_fields": ["file_path", "content"],
                    "expected": "At least one of file_path or content must be provided",
                    "actual_values": {"file_path": file_path, "content": content},
                    "suggestion": (
                        "Provide either the file_path parameter (path to tabular file) "
                        "or the content parameter (string content) for tabular processing."
                    ),
                }
                raise ValidationError(
                    "Either file_path or content must be provided for tabular processing",
                    context=error_context,
                )
            rows = list(csv.DictReader(content_str.splitlines()))
            return rows
        except csv.Error as e:
            operation = f"parsing CSV from {file_path or 'content string'}"
            self.handle_processing_error(e, operation)
            error_context = {
                "agent_name": self.agent_name,
                "file_path": file_path,
                "loader_type": "tabular",
            }
            raise AgentActionsError("Invalid CSV data", context=error_context, cause=e) from e
        except OSError as e:
            self.handle_processing_error(e, f"reading tabular file {file_path}")
            error_context = {
                "agent_name": self.agent_name,
                "file_path": file_path,
                "loader_type": "tabular",
            }
            raise AgentActionsError(
                "Could not read tabular file", context=error_context, cause=e
            ) from e
        except Exception as e:
            self.handle_processing_error(e, "processing tabular file")
            error_context = {
                "agent_name": self.agent_name,
                "file_path": file_path,
                "loader_type": "tabular",
            }
            raise AgentActionsError(
                "Failed to process tabular data", context=error_context, cause=e
            ) from e

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in {".csv", ".tsv"}
