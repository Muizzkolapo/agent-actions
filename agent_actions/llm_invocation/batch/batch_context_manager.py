"""
Batch Context Manager.

Handles persistence of batch context maps.
Extracted from BatchService as part of Phase 4 refactoring.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from agent_actions.utilities.utils_path_utils import ensure_directory_exists
from agent_actions.shared.exceptions import ProcessingError

logger = logging.getLogger(__name__)


class BatchContextManager:
    """
    Manages batch context map lifecycle.

    Handles saving and loading context maps to/from the batch directory.
    Separates context persistence from business logic.

    Example:
        manager = BatchContextManager()

        # Save context
        manager.save_batch_context_map(
            context_map={'rec_1': {...}},
            output_directory='/tmp/node_1_Agent',
            batch_name='test.json'
        )

        # Load context
        context = manager.load_batch_context_map(
            output_directory='/tmp/node_1_Agent',
            batch_name='test.json'
        )
    """

    @staticmethod
    def save_batch_context_map(
        context_map: Dict[str, Any],
        output_directory: str,
        batch_name: str
    ) -> Path:
        """
        Save batch processing context map to batch directory.

        Args:
            context_map: Context map to save
            output_directory: Output directory path
            batch_name: Batch file name

        Returns:
            Path where context was saved

        Raises:
            ProcessingError: If save fails
        """
        try:
            context_path = BatchContextManager._get_context_path(
                output_directory, batch_name
            )

            # Ensure directory exists
            ensure_directory_exists(context_path, is_file=True)

            # Save context map
            with open(context_path, 'w', encoding='utf-8') as f:
                json.dump(context_map, f, indent=2, ensure_ascii=False)

            logger.debug("Saved context map to %s (%d entries)",
                        context_path, len(context_map))

            return context_path

        except Exception as e:
            raise ProcessingError(
                f"Failed to save context map: {e}",
                cause=e,
                context={
                    'output_directory': output_directory,
                    'batch_name': batch_name
                }
            ) from e

    @staticmethod
    def load_batch_context_map(
        output_directory: str,
        batch_name: str
    ) -> Dict[str, Any]:
        """
        Load batch processing context map from batch directory.

        Args:
            output_directory: Output directory path
            batch_name: Batch file name

        Returns:
            Loaded context map

        Raises:
            ProcessingError: If load fails or file not found
        """
        try:
            context_path = BatchContextManager._get_context_path(
                output_directory, batch_name
            )

            if not context_path.exists():
                raise ProcessingError(
                    f"Context map file not found: {context_path}",
                    context={
                        'output_directory': output_directory,
                        'batch_name': batch_name
                    }
                )

            with open(context_path, 'r', encoding='utf-8') as f:
                context_map = json.load(f)

            logger.debug("Loaded context map from %s (%d entries)",
                        context_path, len(context_map))

            return context_map

        except json.JSONDecodeError as e:
            raise ProcessingError(
                f"Invalid JSON in context map file: {e}",
                cause=e,
                context={
                    'output_directory': output_directory,
                    'batch_name': batch_name
                }
            ) from e
        except Exception as e:
            if isinstance(e, ProcessingError):
                raise
            raise ProcessingError(
                f"Failed to load context map: {e}",
                cause=e,
                context={
                    'output_directory': output_directory,
                    'batch_name': batch_name
                }
            ) from e

    @staticmethod
    def batch_context_exists(
        output_directory: str,
        batch_name: str
    ) -> bool:
        """
        Check if batch context map file exists.

        Args:
            output_directory: Output directory path
            batch_name: Batch file name

        Returns:
            True if context map exists
        """
        context_path = BatchContextManager._get_context_path(
            output_directory, batch_name
        )
        return context_path.exists()

    @staticmethod
    def _get_context_path(output_directory: str, batch_name: str) -> Path:
        """
        Get path to context map file.

        Args:
            output_directory: Output directory path (e.g., '.../target/node_1_Agent')
            batch_name: Batch file name (e.g., 'input.json')

        Returns:
            Path to context map file (e.g., '.../target/node_1_Agent/batch/.context_map_input.json')
        """
        output_dir = Path(output_directory)
        batch_dir = output_dir / 'batch'

        # Context file name: .context_map_{batch_name}
        context_file_name = f'.context_map_{batch_name}'

        return batch_dir / context_file_name

    @staticmethod
    def delete_batch_context_map(
        output_directory: str,
        batch_name: str
    ) -> bool:
        """
        Delete batch context map file if it exists.

        Args:
            output_directory: Output directory path
            batch_name: Batch file name

        Returns:
            True if file was deleted, False if it didn't exist
        """
        context_path = BatchContextManager._get_context_path(
            output_directory, batch_name
        )

        if context_path.exists():
            context_path.unlink()
            logger.debug("Deleted context map at %s", context_path)
            return True

        return False
