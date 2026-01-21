"""Utility for splitting outputs into main and side outputs."""

from typing import List, Dict, Any, Tuple


def split_main_and_side_outputs(processed_items: List[Dict[str, Any]]) -> Tuple[List, List]:
    """
    Split processed items into main and side outputs.

    Args:
        processed_items: List of processed data items

    Returns:
        Tuple of (main_output, side_output) lists
    """
    main_output, side_output = ([], [])
    for item in processed_items:
        content = item.get("content", {})
        if isinstance(content, dict) and content.get("side_output", False):
            side_output.append(item)
        else:
            main_output.append(item)
    return (main_output, side_output)
