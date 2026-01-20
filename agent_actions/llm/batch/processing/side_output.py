"""
Side Output Handler.

Handles separation and persistence of side output data from batch processing.
Extracted from BatchService for better separation of concerns.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

from agent_actions.utils.path_utils import ensure_directory_exists

logger = logging.getLogger(__name__)


class BatchSideOutputHandler:
    """
    Handles side output operations for batch processing.

    Side outputs are special items marked with {'content': {'side_output': True}}
    that need to be stored separately from main workflow output.

    Example:
        handler = BatchSideOutputHandler()
        main_output, side_output = handler.separate(processed_items)
        if side_output:
            handler.save(side_output, '/path/to/side_output.json')
    """

    @staticmethod
    def separate(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Split processed items into main and side output collections.

        Args:
            items: List of processed items from batch results

        Returns:
            Tuple of (main_output, side_output) lists
        """
        main_output, side_output = ([], [])
        for item in items:
            content = item.get("content", {})
            if isinstance(content, dict) and content.get("side_output", False):
                side_output.append(item)
            else:
                main_output.append(item)
        return (main_output, side_output)

    @staticmethod
    def save(data: List[Dict[str, Any]], file_path: Path) -> None:
        """
        Persist side output data, merging with existing content if present.

        Args:
            data: Side output data to save
            file_path: Path to save the side output file
        """
        ensure_directory_exists(file_path, is_file=True)
        existing = []
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Corrupted side output file %s, starting fresh: %s",
                        file_path,
                        e,
                        extra={
                            "file_path": str(file_path),
                            "operation": "side_output_load",
                            "error_position": f"line {e.lineno}, col {e.colno}",
                        },
                    )
                    existing = []
        if not isinstance(existing, list):
            existing = [existing]
        if not isinstance(data, list):
            data = [data]
        existing.extend(data)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4)
