"""Data loader for batch processing from JSON and JSONL files."""

import io
import json
from pathlib import Path
from typing import Any

from agent_actions.config.interfaces import IDataLoader, ProcessingMode
from agent_actions.input.loaders.base import read_file_with_retry


class BatchDataLoader(IDataLoader):
    """Loads data for batch processing from a specified file path.

    Delegates file I/O to :func:`read_file_with_retry` from the
    centralised loader infrastructure, gaining automatic retry on
    transient I/O errors.
    """

    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def load_data(self, file_path: str) -> list[dict[str, Any]]:
        """Load data from a JSON or JSONL file."""
        path = Path(file_path)
        suffix = path.suffix
        if suffix not in (".json", ".jsonl"):
            raise ValueError(f"Unsupported file type: {suffix}. Please use .json or .jsonl.")
        try:
            content = read_file_with_retry(file_path)
            if suffix == ".jsonl":
                return [json.loads(line) for line in io.StringIO(content) if line.strip()]
            data = json.loads(content)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {file_path}: {e}") from e
