"""Shared source content resolution for non-first-stage records.

Single implementation used by task_preparer.py and guard_context.py.
Resolution by identity: own guid -> carried parent_source_guid -> the source
namespace the record carries -> None. Same order as the FILE-mode resolver in
prompt/context/scope_application.py, so a record resolves to one document
whichever granularity reads it. The source contract is enforced downstream in
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

    1. Own source_guid, then the record's carried parent_source_guid (a pool
       identity a minted row carries — its producer, or the ancestor inherited
       from the input standing in for its namespaces) -> look up by guid. The
       pool is the run's current source set; the namespace a record carries is
       a copy taken when it was written, so identity is read first.
    2. Neither identity resolves -> the record itself, when it carries a
       ``source`` namespace. That is all a record the pool cannot place has,
       and it must be a namespace: returning the record on the strength of the
       key alone exposes its own action-output namespaces as the source
       document, which is case 3's failure wearing a resolved answer's clothes.
    3. Neither identity resolves against a non-empty pool and the record
       carries no namespace -> None. Never the item itself -- that would expose
       the record's own action-output namespaces as if they were the source
       document.
    """
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

    record_content = item.get("content", {})
    if isinstance(record_content, dict) and isinstance(record_content.get("source"), dict):
        return item

    logger.debug(
        "Could not resolve source content for action '%s' "
        "(guid=%s, parent_guid=%s, source_data=%s) — no source namespace available",
        action_name,
        source_guid,
        item.get("parent_source_guid"),
        "available" if source_data else "None",
    )
    return None
