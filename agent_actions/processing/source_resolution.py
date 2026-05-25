"""Shared source content resolution for online and batch paths.

Single point of change for the source namespace contract:
prefer record envelope's 'source' sub-namespace, else look up by
source_guid from source_data, else fall back to the record itself.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_source_content(
    item: dict[str, Any],
    source_guid: str | None,
    source_data: list[dict[str, Any]] | None,
) -> Any:
    """Resolve source content for a non-first-stage record.

    Resolution order:
    1. Record's content envelope has a "source" key → return the record
       (SourceNamespaceBuilder will extract the sub-namespace).
    2. source_guid + source_data available → look up by guid.
    3. Fall back to the record itself.
    """
    # Fast path: record already carries the source namespace
    record_content = item.get("content", {}) if isinstance(item, dict) else {}
    if isinstance(record_content, dict) and "source" in record_content:
        return item

    # Batch fallback: look up original staging record by guid
    if source_guid and source_data:
        from agent_actions.input.preprocessing.transformation.transformer import (
            DataTransformer,
        )

        source_content = DataTransformer.get_content_by_source_guid(
            source_data, source_guid
        )
        if source_content is not None:
            return source_content

    return item
