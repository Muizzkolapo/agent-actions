"""Shared path security utilities for seed data resolution.

Both the pre-flight resolution service and the runtime StaticDataLoader
call ``resolve_seed_path`` so that path-traversal prevention logic exists
in exactly one place.
"""

from pathlib import Path

FILE_PREFIX = "$file:"


def resolve_seed_path(file_spec: str, base_dir: Path) -> Path:
    """Parse a ``$file:`` reference, resolve against *base_dir*, and validate.

    Returns the resolved absolute ``Path``.

    Raises:
        ValueError: If the spec is empty, escapes *base_dir* via traversal,
            or is otherwise invalid.
    """
    if not file_spec:
        raise ValueError("Empty file spec")

    # Strip $file: prefix if present
    file_path = file_spec[len(FILE_PREFIX) :] if file_spec.startswith(FILE_PREFIX) else file_spec

    if not file_path:
        raise ValueError(f"Empty path after prefix in: {file_spec}")

    resolved = (base_dir / file_path).resolve()

    # Security: prevent path traversal outside base_dir
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise ValueError(
            f"Seed file path escapes base directory: {file_spec} "
            f"(resolved to {resolved}, base is {base_dir.resolve()})"
        ) from None

    return resolved
