"""Shared utilities for Agent Actions LSP."""

from pathlib import Path
from typing import List


def uri_to_path(uri: str) -> Path:
    """Convert file:// URI to Path.

    Args:
        uri: A file:// URI string (e.g., "file:///path/to/file.yaml")

    Returns:
        Path object representing the file path.
    """
    return Path(uri.replace("file://", ""))


def is_in_dependencies_context(lines: List[str], current_line: int) -> bool:
    """Check if current line is within a dependencies block.

    Looks backwards from the current line to find a "dependencies:" keyword
    at the same or lower indentation level.

    Args:
        lines: List of all lines in the document.
        current_line: Zero-based line number to check.

    Returns:
        True if the line is within a dependencies block, False otherwise.
    """
    current_indent = len(lines[current_line]) - len(lines[current_line].lstrip())

    for i in range(current_line - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue

        line_indent = len(line) - len(line.lstrip())

        # If we hit a line with less indentation, stop
        if line_indent < current_indent and not line.strip().startswith("-"):
            if line.strip().startswith("dependencies:"):
                return True
            return False

        if line.strip().startswith("dependencies:"):
            return True

    return False


def is_in_context_scope_list(lines: List[str], current_line: int) -> bool:
    """Check if current line is within a context_scope observe/drop/passthrough list.

    Looks backwards from the current line to find observe:, drop:, or passthrough:
    keywords nested under a context_scope: block.

    Args:
        lines: List of all lines in the document.
        current_line: Zero-based line number to check.

    Returns:
        True if the line is within a context_scope list block, False otherwise.
    """
    current_indent = len(lines[current_line]) - len(lines[current_line].lstrip())
    list_block_indent = None

    for i in range(current_line - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())

        if list_block_indent is None and line_indent < current_indent:
            if line.strip().startswith(("observe:", "drop:", "passthrough:")):
                list_block_indent = line_indent
                current_indent = line_indent
                continue

        if list_block_indent is not None and line_indent < list_block_indent:
            return line.strip().startswith("context_scope:")

    return False
