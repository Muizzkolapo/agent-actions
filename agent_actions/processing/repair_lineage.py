"""What a repair rewrote at each action, for the actions below it in the same run.

A repair names records by identity, and an action that splits a record gives each row it
writes an identity of its own. The actions below are handed those rows, so a repair that
re-runs the split names them there too, and takes out what those actions built on the
rows the split replaced. Both are read off what the action wrote in this run, never off
``parent_source_guid``, which names the first ancestor and so every row below a second
split alike. Keyed by the run's backend, as the disposition gate keys what a repair found:
``agac retry`` runs a workflow in the process that just finished one.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

# Per action, the rows an action above it wrote, and those it took away, in this repair.
_WRITTEN_ABOVE: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()
_GONE_ABOVE: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()


def note_rewritten_by_repair(
    storage_backend: Any,
    below: Iterable[str],
    before: Iterable[dict[str, Any]],
    after: Iterable[dict[str, Any]],
) -> None:
    """Note for each action in *below* what a repair changed in one file of the action above.

    *before* and *after* are that file as stored before the action ran and once it was
    written. A row only *after* holds is one no action below has answered; a row only
    *before* held is gone, and so is whatever an action below built on it.
    """
    if storage_backend is None:
        return
    held_before = _identities(before)
    held_after = _identities(after)
    written = held_after - held_before
    gone = held_before - held_after
    if not (written or gone):
        return
    for action in below:
        _WRITTEN_ABOVE.setdefault(storage_backend, {}).setdefault(action, set()).update(written)
        _GONE_ABOVE.setdefault(storage_backend, {}).setdefault(action, set()).update(gone)


def written_above(storage_backend: Any, action_name: str) -> frozenset[str]:
    """The rows actions above *action_name* wrote in this repair, which it names too."""
    return _noted(_WRITTEN_ABOVE, storage_backend, action_name)


def gone_above(storage_backend: Any, action_name: str) -> frozenset[str]:
    """The rows actions above *action_name* took away in this repair."""
    return _noted(_GONE_ABOVE, storage_backend, action_name)


def drop_rows_built_on_rows_gone_above(
    storage_backend: StorageBackend | None,
    action_name: str,
    relative_path: str | None,
    inputs: Any,
    repairing: Collection[str],
) -> list[dict[str, Any]]:
    """Take out of *relative_path* what *action_name* built on rows gone above it.

    Returns the file as it was stored before, for ``note_rewritten_by_repair``. A row is
    built on a gone row when it is stored under its identity, or names it as parent or
    producer: a tombstone under a record the split above now answers with rows of their
    own, or a row made from a split row the split replaced. Each such row stands for an
    input the repair hands this action again under a new identity, so it is taken out
    with what this action holds a disposition for, rather than carried beside the answer
    the repair writes. Written before the action runs, so the batch path, which stores
    its answers in a later run, does not carry it either. A gone identity still among
    the inputs this action is not asked to answer again is left alone.
    """
    if storage_backend is None or not relative_path:
        return []
    try:
        stored = storage_backend.read_target_for_rewrite(action_name, relative_path)
    except FileNotFoundError:
        return []
    gone = gone_above(storage_backend, action_name)
    if not gone:
        return stored
    offered = _identities(inputs if isinstance(inputs, list) else [])
    gone = gone - (offered - frozenset(repairing))
    stale = [row for row in stored if _built_on(row, gone)]
    if not stale:
        return stored
    logger.info(
        "Action '%s': %d stored row(s) of %s were built on rows the repair replaced above "
        "it, so they are taken out and their inputs answered again",
        action_name,
        len(stale),
        relative_path,
    )
    kept = [row for row in stored if not _built_on(row, gone)]
    storage_backend.write_target(action_name, relative_path, kept)
    forgotten = (_identities(stale) | gone) - offered
    if forgotten:
        storage_backend.clear_dispositions_batch(action_name, sorted(forgotten))
    return stored


def _built_on(row: dict[str, Any], gone: frozenset[str]) -> bool:
    return (
        row.get("source_guid") in gone
        or row.get("parent_source_guid") in gone
        or not gone.isdisjoint(row.get("producer_source_guids") or ())
    )


def _identities(rows: Iterable[Any]) -> set[str]:
    return {guid for row in rows if isinstance(row, dict) and (guid := row.get("source_guid"))}


def _noted(
    registry: WeakKeyDictionary[Any, dict[str, set[str]]], storage_backend: Any, action_name: str
) -> frozenset[str]:
    if storage_backend is None:
        return frozenset()
    return frozenset(registry.get(storage_backend, {}).get(action_name, ()))
