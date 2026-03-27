"""Persistence of batch context maps to/from the batch directory."""

import json
import logging
from pathlib import Path
from typing import Any

from agent_actions.errors import ProcessingError
from agent_actions.utils.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


class BatchContextManager:
    """Saves and loads batch context maps to/from the batch directory."""

    @staticmethod
    def save_batch_context_map(
        context_map: dict[str, Any], output_directory: str, batch_name: str
    ) -> Path:
        """Save batch processing context map to batch directory.

        Raises:
            ProcessingError: If save fails
        """
        try:
            context_path = BatchContextManager._get_context_path(output_directory, batch_name)

            ensure_directory_exists(context_path, is_file=True)

            with open(context_path, "w", encoding="utf-8") as f:
                json.dump(context_map, f, indent=2, ensure_ascii=False)

            logger.debug("Saved context map to %s (%d entries)", context_path, len(context_map))

            return context_path

        except Exception as e:
            raise ProcessingError(
                f"Failed to save context map: {e}",
                cause=e,
                context={"output_directory": output_directory, "batch_name": batch_name},
            ) from e

    @staticmethod
    def load_batch_context_map(output_directory: str, batch_name: str) -> dict[str, Any]:
        """Load batch processing context map from batch directory.

        Raises:
            ProcessingError: If load fails or file not found
        """
        try:
            context_path = BatchContextManager._get_context_path(output_directory, batch_name)

            if not context_path.exists():
                raise ProcessingError(
                    f"Context map file not found: {context_path}",
                    context={"output_directory": output_directory, "batch_name": batch_name},
                )

            with open(context_path, encoding="utf-8") as f:
                context_map = json.load(f)

            logger.debug("Loaded context map from %s (%d entries)", context_path, len(context_map))

            return context_map  # type: ignore[no-any-return]

        except json.JSONDecodeError as e:
            raise ProcessingError(
                f"Invalid JSON in context map file: {e}",
                cause=e,
                context={"output_directory": output_directory, "batch_name": batch_name},
            ) from e
        except Exception as e:
            if isinstance(e, ProcessingError):
                raise
            raise ProcessingError(
                f"Failed to load context map: {e}",
                cause=e,
                context={"output_directory": output_directory, "batch_name": batch_name},
            ) from e

    @staticmethod
    def batch_context_exists(output_directory: str, batch_name: str) -> bool:
        """Check if batch context map file exists."""
        context_path = BatchContextManager._get_context_path(output_directory, batch_name)
        return context_path.exists()

    @staticmethod
    def _get_context_path(output_directory: str, batch_name: str) -> Path:
        """Get path to context map file."""
        output_dir = Path(output_directory)
        batch_dir = output_dir / "batch"

        if ".." in batch_name:
            raise ValueError(f"Invalid batch name contains path traversal: {batch_name}")
        safe_name = Path(batch_name).name

        context_file_name = f".context_map_{safe_name}"

        return batch_dir / context_file_name

    @staticmethod
    def delete_batch_context_map(output_directory: str, batch_name: str) -> bool:
        """Delete batch context map file if it exists."""
        context_path = BatchContextManager._get_context_path(output_directory, batch_name)

        if context_path.exists():
            context_path.unlink()
            logger.debug("Deleted context map at %s", context_path)
            return True

        return False
