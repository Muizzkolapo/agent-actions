"""JSON serialisation safety utilities.

Provides sanitisation of Python objects so that ``json.dumps()``
never produces invalid JSON (NaN, Infinity) or raises ``TypeError`` on
non-serialisable types (bytes, sets, datetime).

Applied at serialisation boundaries — just before data is handed to
provider SDKs or written to JSONL files.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


def ensure_json_safe(obj: Any) -> Any:
    """Convert non-JSON-serialisable types to safe representations, at any nesting depth.

    Handles types that ``json.dumps()`` either rejects (``TypeError``) or
    serialises into tokens that are invalid JSON (``NaN``, ``Infinity``).

    Type conversions:
        * ``float('nan')`` / ``float('inf')`` → ``None``
        * ``bytes`` → UTF-8 decoded ``str``
        * ``set`` / ``frozenset`` → ``list``
        * ``tuple`` → ``list``
        * ``datetime`` / ``date`` → ISO-8601 ``str``
        * Non-string dict keys → ``str(key)``
        * Other non-serialisable objects → ``str(obj)``

    Warnings are logged for NaN/Infinity replacements and unknown-type
    fallbacks so that upstream producers can be fixed. A value nested past the
    interpreter's recursion limit is converted again on an explicit stack, with
    the same result; a container that holds itself raises ``ValueError``.
    """
    try:
        return _convert_recursively(obj)
    except RecursionError:
        return _convert_without_recursion(obj)


def _convert_recursively(obj: Any) -> Any:
    safe, members = _convert(obj)
    if members is None:
        return safe
    if isinstance(safe, dict):
        for key, value in members:
            safe[key] = _convert_recursively(value)
    else:
        for _, value in members:
            safe.append(_convert_recursively(value))
    return safe


def _convert_without_recursion(obj: Any) -> Any:
    root: list[Any] = []
    open_containers: set[int] = set()
    stack: list[tuple[Iterator[tuple[Any, Any]], dict[str, Any] | list[Any], int]] = [
        (iter(((None, obj),)), root, -1)
    ]
    while stack:
        members, target, marker = stack[-1]
        for key, value in members:
            safe, children = _convert(value)
            if isinstance(target, dict):
                target[key] = safe
            else:
                target.append(safe)
            if children is not None:
                if id(value) in open_containers:
                    raise ValueError("Circular reference detected")
                open_containers.add(id(value))
                stack.append((children, safe, id(value)))
                break
        else:
            stack.pop()
            open_containers.discard(marker)
    return root[0]


def _convert(obj: Any) -> tuple[Any, Iterator[tuple[Any, Any]] | None]:
    """A leaf's safe value, or an empty container plus the members still to convert into it."""
    if obj is None or isinstance(obj, (bool, str)):
        # bool before int: bool is a subclass of int in Python
        return obj, None
    if isinstance(obj, int):
        return obj, None
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            logger.warning("Replacing non-finite float %r with null for JSON safety", obj)
            return None, None
        return obj, None
    if isinstance(obj, dict):
        return {}, ((str(k), v) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return [], ((None, item) for item in obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace"), None
    if isinstance(obj, (set, frozenset)):
        return [], ((None, item) for item in obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat(), None
    logger.warning(
        "Converting non-serialisable type %s to string for JSON safety",
        type(obj).__name__,
    )
    return str(obj), None
