"""What a repair rewrote at each action, for the actions below it in the same run.

A repair names records by identity, and an action that splits a record gives each row it
writes an identity of its own. The actions below are handed those rows, so a repair that
re-runs the split names them there too, and takes out what those actions built on the
rows the split replaced. Both are read off what the action wrote in this run, never off
``parent_source_guid``, which names the first ancestor and so every row below a second
split alike. Keyed by the run's backend, as the disposition gate keys what a repair found:
``agac retry`` runs a workflow in the process that just finished one.

A retry keeps the notes in a file as they are made (``keep_notes_at``). Stopped before
an action below ran, it leaves them for the retry that resumes it: that one re-runs the
split over the rows the stopped one wrote, so it sees only those taken away, not the
rows of the failed run the action below still holds (``resume_notes``).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from agent_actions.utils.atomic_write import atomic_json_write

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

# Per action, the rows an action above it wrote, and those it took away, in this repair.
_WRITTEN_ABOVE: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()
_GONE_ABOVE: WeakKeyDictionary[Any, dict[str, set[str]]] = WeakKeyDictionary()
# Where a repair keeps its notes, and the retry they belong to.
_KEPT_AT: WeakKeyDictionary[Any, tuple[Path, str]] = WeakKeyDictionary()
# Actions of one level note from several threads at once.
_NOTING = threading.Lock()


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
    with _NOTING:
        for action in below:
            _WRITTEN_ABOVE.setdefault(storage_backend, {}).setdefault(action, set()).update(written)
            _GONE_ABOVE.setdefault(storage_backend, {}).setdefault(action, set()).update(gone)
        _write_kept(storage_backend)


def keep_notes_at(storage_backend: Any, path: Path, created_at: str) -> None:
    """Keep this repair's notes in *path*, under the retry *created_at*, as they are made."""
    if storage_backend is None:
        return
    with _NOTING:
        _KEPT_AT[storage_backend] = (path, created_at)
        _write_kept(storage_backend)


def notes_kept_at(path: Path, created_at: str | None) -> dict[str, dict[str, list[str]]]:
    """The notes kept in *path* by the retry *created_at*; empty for any other or none."""
    if not created_at:
        return {}
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        logger.warning("Could not read the repair notes in %s: %s", path, error)
        return {}
    if not isinstance(kept, dict) or kept.get("created_at") != created_at:
        return {}
    return {kind: kept.get(kind) or {} for kind in ("written", "gone")}


def resume_notes(
    storage_backend: Any, kept: dict[str, dict[str, list[str]]], actions: Collection[str]
) -> None:
    """Note again, for each of *actions*, what a stopped repair noted for it.

    Only for actions that repair never ran after noting: one it ran has already taken
    out what the notes name, and may since hold rows that name it as an ancestor.
    """
    if storage_backend is None:
        return
    with _NOTING:
        for kind, registry in (("written", _WRITTEN_ABOVE), ("gone", _GONE_ABOVE)):
            for action, identities in (kept.get(kind) or {}).items():
                if action in actions:
                    registry.setdefault(storage_backend, {}).setdefault(action, set()).update(
                        identities
                    )


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


def _write_kept(storage_backend: Any) -> None:
    kept_at = _KEPT_AT.get(storage_backend)
    if kept_at is None:
        return
    path, created_at = kept_at
    notes = {
        kind: {action: sorted(ids) for action, ids in registry.get(storage_backend, {}).items()}
        for kind, registry in (("written", _WRITTEN_ABOVE), ("gone", _GONE_ABOVE))
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, {"created_at": created_at, **notes}, indent=2)
    except OSError as error:
        logger.warning(
            "Could not keep the repair notes in %s (%s); a retry resuming this one after "
            "an interrupt may keep rows built on what this one replaced",
            path,
            error,
        )


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
    with _NOTING:
        return frozenset(registry.get(storage_backend, {}).get(action_name, ()))
