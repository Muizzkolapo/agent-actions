"""Batch source data persistence handler."""

from pathlib import Path
from typing import Dict, List, Any, Union, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class BatchSourceHandler:
    """
    Handles batch source data persistence.

    Delegates to UnifiedSourceDataSaver for file locking, deduplication,
    and source saving.
    """

    def save_task_source(
        self,
        src_text: Union[Dict[str, Any], List[Dict[str, Any]]],
        file_path: str,
        base_directory: str,
        _output_directory: str,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> None:
        """
        Save task source data using unified source saver.

        Args:
            src_text: Single item (Dict) or list of items (List[Dict]) in flat format
                     with 'source_guid' field. Accepts both for convenience.
            file_path: Path to the file being processed
            base_directory: Base directory for input files
            _output_directory: Output directory for processed files (unused)
        """
        from agent_actions.output.saver import UnifiedSourceDataSaver

        relative_path = Path(file_path).relative_to(base_directory)

        base_path = Path(base_directory)
        parts = base_path.parts
        if "agent_io" in parts:
            agent_io_idx = parts.index("agent_io")
            workflow_root = Path(*parts[:agent_io_idx])
        else:
            workflow_root = base_path.parent.parent.parent

        saver = UnifiedSourceDataSaver(
            base_directory=str(workflow_root),
            enable_deduplication=True,
            storage_backend=storage_backend,
        )

        saver.save_source_items(items=src_text, relative_path=str(relative_path.with_suffix("")))
