"""Shared utilities for Agent Actions LSP."""

import urllib.parse
from pathlib import Path


def uri_to_path(uri: str) -> Path:
    """Convert file:// URI to Path, handling URL-encoding and Windows drive letters."""
    parsed = urllib.parse.urlparse(uri)
    path = urllib.parse.unquote(parsed.path)
    # Preserve UNC host: file://server/share → //server/share
    # "localhost" is the local machine per RFC 8089, not a network share.
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        return Path(f"//{parsed.netloc}{path}")
    # On Windows, urlparse("file:///C:/path").path is "/C:/path";
    # strip the leading slash so Path resolves the drive letter correctly.
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)


def is_in_dependencies_context(lines: list[str], current_line: int) -> bool:
    """Check if current line is within a dependencies block."""
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


def is_in_context_scope_list(lines: list[str], current_line: int) -> bool:
    """Check if current line is within a context_scope observe/drop/passthrough list."""
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
