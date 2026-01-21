"""Batch source data persistence handler."""

from pathlib import Path
from typing import Dict, List, Any, Union


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

        # Calculate paths for source saving
        # Find workflow root by looking for 'agent_io' in the path and going up one level
        # base_directory could be:
        #   - .../qanalabs_quiz_gen/agent_io/staging (2 levels to root)
        #   - .../qanalabs_quiz_gen/agent_io/target/node_X (3 levels to root)
        relative_path = Path(file_path).relative_to(base_directory)

        # Find workflow root by traversing up until we find the parent of 'agent_io'
        base_path = Path(base_directory)
        workflow_root = base_path
        for parent in base_path.parents:
            if (parent / "agent_io").exists() or parent.name != "agent_io":
                if (parent / "agent_io") == base_path or (parent / "agent_io") in base_path.parents:
                    workflow_root = parent
                    break

        # Simpler approach: find 'agent_io' in path parts and get its parent
        parts = base_path.parts
        if "agent_io" in parts:
            agent_io_idx = parts.index("agent_io")
            workflow_root = Path(*parts[:agent_io_idx])
        else:
            # Fallback to going up 3 levels
            workflow_root = base_path.parent.parent.parent

        # Use unified saver with batch mode settings (locking + deduplication)
        saver = UnifiedSourceDataSaver(
            base_directory=str(workflow_root), enable_deduplication=True, enable_locking=True
        )

        # Save source items (relative_path without extension for consistency)
        # UnifiedSourceDataSaver will create: workflow_root/agent_io/source/{relative_path}.json
        saver.save_source_items(items=src_text, relative_path=str(relative_path.with_suffix("")))
