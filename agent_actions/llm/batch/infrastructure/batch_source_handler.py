"""Batch source data persistence handler."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend


class BatchSourceHandler:
    """Handles batch source data persistence via UnifiedSourceDataSaver."""

    def save_task_source(
        self,
        src_text: dict[str, Any] | list[dict[str, Any]],
        file_path: str,
        base_directory: str,
        _output_directory: str,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> None:
        """Save task source data using unified source saver."""
        from agent_actions.output.saver import UnifiedSourceDataSaver
        from agent_actions.utils.path_utils import derive_workflow_root

        relative_path = Path(file_path).relative_to(base_directory)
        workflow_root = derive_workflow_root(base_directory)

        saver = UnifiedSourceDataSaver(
            base_directory=str(workflow_root),
            enable_deduplication=True,
            storage_backend=storage_backend,
        )

        saver.save_source_items(items=src_text, relative_path=str(relative_path.with_suffix("")))
