"""Shared source content resolution for non-first-stage records.

Single implementation used by task_preparer.py and guard_context.py.
Resolution by identity: content envelope source key -> own guid -> carried
parent_source_guid -> None. The source contract is enforced downstream in
scope_builder.py.
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
    """Resolve source content for a non-first-stage record by identity.

    1. Record content has "source" key -> return record (already source-shaped)
    2. Own source_guid, then the record's carried parent_source_guid (the
       original pool identity, preserved when expansion re-mints guids) ->
       look up by guid
    3. Neither identity resolves against a non-empty pool -> None. Never the
       item itself -- that would expose the record's own action-output
       namespaces as if they were the source document.
    """
    record_content = item.get("content", {})
    if isinstance(record_content, dict) and "source" in record_content:
        return item

    if source_data:
        from agent_actions.input.preprocessing.transformation.transformer import (
            DataTransformer,
        )

        if source_guid:
            result = DataTransformer.get_content_by_source_guid(source_data, source_guid)
            if result is not None:
                return result

        parent_source_guid = item.get("parent_source_guid")
        if parent_source_guid:
            result = DataTransformer.get_content_by_source_guid(source_data, parent_source_guid)
            if result is not None:
                return result

    logger.debug(
        "Could not resolve source content for action '%s' "
        "(guid=%s, parent_guid=%s, source_data=%s) — no source namespace available",
        action_name,
        source_guid,
        item.get("parent_source_guid"),
        "available" if source_data else "None",
    )
    return None
