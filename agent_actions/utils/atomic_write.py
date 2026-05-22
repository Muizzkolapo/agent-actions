"""Atomic JSON file writes — temp file, fsync, rename.

Prevents crash-corrupted state files by ensuring the target path
is either the old content or the new content, never a partial write.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_json_write(
    path: Path,
    data: Any,
    *,
    fsync: bool = True,
    **json_kwargs: Any,
) -> None:
    """Write JSON data to *path* atomically.

    Writes to a temporary file in the same directory, optionally fsyncs
    to disk, then renames to the target. If anything fails, the temp file
    is cleaned up and the original file (if any) is left untouched.

    Args:
        path: Target file path (must be a concrete path, not a string).
        data: JSON-serializable data.
        fsync: Whether to fsync before rename (default True). Disable only
               for non-critical data where speed matters more than durability.
        **json_kwargs: Forwarded to ``json.dump`` (e.g. ``indent=2``,
                       ``ensure_ascii=False``).

    Raises:
        OSError: If the write or rename fails. The original exception is
                 chained via ``from``.
    """
    fd, tmp_path_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp", prefix=path.stem + "_")
    tmp_path = Path(tmp_path_str)

    try:
        f = os.fdopen(fd, "w", encoding="utf-8")
    except Exception:
        os.close(fd)
        tmp_path.unlink(missing_ok=True)
        raise

    try:
        with f:
            json.dump(data, f, **json_kwargs)
            if fsync:
                f.flush()
                os.fsync(f.fileno())

        tmp_path.replace(path)

    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise OSError(f"Failed to write {path}: {e}") from e
