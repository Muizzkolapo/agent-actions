"""Shared source content resolution for non-first-stage records.

Single implementation used by task_preparer.py and guard_context.py.
Three-tier resolution: content envelope source key -> guid lookup -> fallback to item.
The source contract is enforced downstream in scope_builder.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_source_content(
    item: dict[str, Any],
    source_guid: str | None,
    source_data: list[dict[str, Any]] | None,
    action_name: str = "unknown",
) -> Any:
    """Resolve source content for a non-first-stage record.

    1. Record content has "source" key -> return record
    2. source_guid + source_data -> look up by guid
    3. Fall back to item (scope_builder enforces the source contract)
    """
    record_content = item.get("content", {})
    if isinstance(record_content, dict) and "source" in record_content:
        return item

    if source_guid and source_data:
        from agent_actions.input.preprocessing.transformation.transformer import (
            DataTransformer,
        )

        result = DataTransformer.get_content_by_source_guid(source_data, source_guid)
        if result is not None:
            return result

    logger.debug(
        "Could not resolve source content for action '%s' "
        "(guid=%s, source_data=%s) — falling back to item",
        action_name,
        source_guid,
        "available" if source_data else "None",
    )
    return item
