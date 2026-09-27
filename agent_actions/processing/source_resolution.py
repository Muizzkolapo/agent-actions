"""Shared source content resolution for a record, at either stage.

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
       and it must be a namespace: returned on the strength of the key alone,
       a record whose ``source`` holds a scalar has its own action-output
       namespaces published as the source document instead.
    3. Neither identity resolves against a non-empty pool and the record
       carries no namespace -> None, rather than the record's own content.

    A workflow with no staging data of its own passes its input records as the
    pool (``pipeline.py``: "the input data IS the source"). A record then
    resolves to itself at case 1 by design, and its own content is the source
    document — so case 3's rule binds only where the pool is a separate set.
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


def resolve_first_stage_source(item: Any) -> Any:
    """Resolve source content for a first-stage record, as a record envelope.

    The record IS the input, so its own content is the source document. It is returned
    enveloped because the namespace builder reads an envelope: handed the inner content
    dict it finds no ``content`` key, takes its flat branch and publishes
    ``{"source": payload}`` one level too deep. A record whose user fields sit at the top
    level is normalized first, so ``RECORD_FRAMEWORK_FIELDS`` separates them from the
    framework's own keys -- the boundary such a record does not carry, and without which a
    wildcard ``observe`` sends ``source_guid``, ``node_id`` and ``lineage`` to the model as
    document fields. A non-dict item is returned unchanged; the builder ignores it.
    """
    from agent_actions.utils.content import get_existing_content

    if not isinstance(item, dict):
        return item
    return {"content": get_existing_content(item, is_first_stage=True)}
