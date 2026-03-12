"""Data loader for batch processing from JSON and JSONL files."""

from pathlib import Path
import json
from typing import List, Dict, Any

from agent_actions.config.interfaces import IDataLoader, ProcessingMode


class BatchDataLoader(IDataLoader):
    """Loads data for batch processing from a specified file path."""

    def supports_async(self) -> bool:
        """Return True as this loader supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def load_data(self, file_path: str) -> List[Dict[str, Any]]:
        """Load data from a JSON or JSONL file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"The specified file does not exist: {file_path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                if path.suffix == ".jsonl":
                    return [json.loads(line) for line in f if line.strip()]
                if path.suffix == ".json":
                    return json.load(f)
                raise ValueError(
                    f"Unsupported file type: {path.suffix}. Please use .json or .jsonl."
                )
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {file_path}: {e}") from e
        except Exception as e:
            raise IOError(f"Could not read file: {file_path}") from e
