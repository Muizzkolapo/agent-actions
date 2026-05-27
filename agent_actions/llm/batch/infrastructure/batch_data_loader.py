"""Data loader for batch processing from JSON and JSONL files."""

import asyncio
import io
import json
from pathlib import Path
from typing import Any

from agent_actions.config.interfaces import IDataLoader, ProcessingMode
from agent_actions.input.loaders.base import read_file_with_retry
from agent_actions.utils.path_safety import assert_path_contained


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

    async def load_data_async(
        self, file_path: str, *, allowed_root: Path | None = None
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.load_data, file_path, allowed_root=allowed_root)

    def load_data(
        self, file_path: str, *, allowed_root: Path | None = None
    ) -> list[dict[str, Any]]:
        """Load data from a JSON or JSONL file.

        Args:
            file_path: Path to the JSON or JSONL file.
            allowed_root: If provided, the resolved file path must be
                contained within this directory.  Raises ``ValueError``
                if the path escapes the root (e.g. via ``..`` or symlinks).
        """
        path = Path(file_path)
        if allowed_root is not None:
            path = assert_path_contained(path, allowed_root)
        else:
            path = path.resolve()
        suffix = path.suffix
        if suffix not in (".json", ".jsonl"):
            raise ValueError(f"Unsupported file type: {suffix}. Please use .json or .jsonl.")
        try:
            content = read_file_with_retry(str(path))
            if suffix == ".jsonl":
                return [json.loads(line) for line in io.StringIO(content) if line.strip()]
            data = json.loads(content)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON from {file_path}: {e}") from e
