"""Text content loader implementation."""

# Similar loader pattern is intentional across different file type loaders
import logging
from typing import Any

from agent_actions.errors import FileLoadError
from agent_actions.input.loaders.base import BaseLoader

logger = logging.getLogger(__name__)


class TextLoader(BaseLoader[str]):
    """Loader for text-based content like TXT, MD, PDF, DOCX, and HTML."""

    def process(self, content: Any, file_path: str | None = None) -> str:
        """Load and return text content from a file or in-memory content."""
        try:
            if file_path:
                return self.load_file(file_path)
            if content:
                return str(content)

            error = ValueError("Either file_path or content must be provided")
            self.handle_validation_error(error, "text input", file_path=file_path)
            raise error
        except FileLoadError:
            raise
        except Exception as e:
            self.handle_processing_error(e, "Processing text content", file_path=file_path)
            raise

    def supports_filetype(self, file_extension: str) -> bool:
        """Return True if the file extension is supported."""
        return file_extension.lower() in {".txt", ".md", ".html"}
