"""JSON serialisation safety utilities.

Provides recursive sanitisation of Python objects so that ``json.dumps()``
never produces invalid JSON (NaN, Infinity) or raises ``TypeError`` on
non-serialisable types (bytes, sets, datetime).

Applied at serialisation boundaries — just before data is handed to
provider SDKs or written to JSONL files.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)


def ensure_json_safe(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable types to safe representations.

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
    fallbacks so that upstream producers can be fixed.
    """
    if obj is None or isinstance(obj, (bool, str)):
        # bool before int: bool is a subclass of int in Python
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            logger.warning("Replacing non-finite float %r with null for JSON safety", obj)
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): ensure_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [ensure_json_safe(item) for item in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (set, frozenset)):
        return [ensure_json_safe(item) for item in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    logger.warning(
        "Converting non-serialisable type %s to string for JSON safety",
        type(obj).__name__,
    )
    return str(obj)
