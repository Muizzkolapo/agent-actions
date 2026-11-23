"""The names a batch keys an input file by, and its context maps in StorageBackend metadata."""

import json
import logging
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from agent_actions.errors import ProcessingError
from agent_actions.storage.backend import batch_file_names_key
from agent_actions.utils import deep_json

if TYPE_CHECKING:
    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def batch_output_name(file_name: str) -> str:
    """The name a batch's output file is stored under, given the input file it answers.

    Finalize writes under it, and submission reads stored rows under it and writes there
    when nothing is sent; two copies of this rule would let one drift and every carried
    input read as having no stored row.
    """
    return PurePosixPath(file_name).with_suffix(".json").as_posix()


def checked_batch_file_name(name: str) -> str:
    """*name*, refused if it would leave the action's input root, or if it holds ``#``.

    A `..` inside a part is part of a name (`v1..2/page.json`), as the store reads it.
    A context map's part keys are its key, then ``#``; a name with ``#`` could spell
    another file's. The store refuses such a name too, so no run stores one.
    """
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid batch file name, outside the input root: {name}")
    if "#" in name:
        raise ValueError(f"Invalid batch file name, it holds '#': {name}")
    return name


def batch_file_identity(
    relative_path: str,
    action_name: str,
    storage_backend: "StorageBackend | None",
    *,
    base_owner: Callable[[str], bool],
    registry: Callable[[str], "BatchRegistryManager"],
) -> str:
    """The name a batch keys an input file by: its path under the action's input root.

    A store written by an older version keyed a file by its basename alone, and holds a
    nested file's rows, batch state and every downstream join under that name. Such a
    file keeps it, unless *base_owner* says a top-level input of the action stores under
    that name, or another nested file stored under it claimed it first. The choice is
    recorded, a repair's too, so two files cannot claim one name, and it outlives a
    reset, since the stored rows do; ``delete_target`` forgets it. *registry* is the
    submission's, so the registry is read once for both.
    """
    identity = PurePosixPath(relative_path).as_posix()
    legacy = PurePosixPath(identity).name
    if legacy == identity or storage_backend is None:
        return identity

    key = batch_file_names_key(action_name)
    names = _recorded_names(storage_backend, key)
    chosen = names.get(identity)
    if chosen == identity:
        return identity
    if chosen == legacy:
        if not base_owner(legacy):
            return legacy
        decided = identity
        logger.info(
            "%s: %s gives the name %s up to a top-level input and moves to %s",
            action_name,
            identity,
            batch_output_name(legacy),
            batch_output_name(identity),
        )
    else:
        decided = identity
        if _stored_under(storage_backend, registry(action_name), action_name, legacy):
            holder = _claimant(names, identity, legacy) or (
                "a top-level input" if base_owner(legacy) else None
            )
            if holder is None:
                decided = legacy
                logger.info(
                    "%s: %s keeps the name %s, under which this store already holds it; "
                    "--fresh moves it to %s",
                    action_name,
                    identity,
                    batch_output_name(legacy),
                    batch_output_name(identity),
                )
            else:
                logger.info(
                    "%s: %s is stored as %s, since %s, which this store already holds, "
                    "belongs to %s; any of its records held there are sent again",
                    action_name,
                    identity,
                    batch_output_name(identity),
                    batch_output_name(legacy),
                    holder,
                )
    names[identity] = decided
    storage_backend.save_metadata(key, json.dumps(names, sort_keys=True))
    return decided


def recorded_batch_file_names(
    storage_backend: "StorageBackend", action_name: str
) -> dict[str, str]:
    """The name chosen for each nested input file of *action_name*, by its identity."""
    return _recorded_names(storage_backend, batch_file_names_key(action_name))


def forget_batch_file_names(
    storage_backend: "StorageBackend", action_name: str, kept: Collection[str]
) -> None:
    """Forget the name chosen for each input file not in *kept*: its rows are gone."""
    key = batch_file_names_key(action_name)
    names = _recorded_names(storage_backend, key)
    left = {identity: chosen for identity, chosen in names.items() if identity in kept}
    if left != names:
        storage_backend.save_metadata(key, json.dumps(left, sort_keys=True))


def _recorded_names(storage_backend: "StorageBackend", key: str) -> dict[str, str]:
    raw = storage_backend.load_metadata(key)
    if raw is None:
        return {}
    try:
        names = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        names = None
    if not isinstance(names, dict):
        logger.warning("Unreadable %s — deciding each nested file's name again", key)
        return {}
    return {k: v for k, v in names.items() if isinstance(k, str) and isinstance(v, str)}


def _claimant(names: dict[str, str], identity: str, legacy: str) -> str | None:
    """Another file already recorded as stored under *legacy*'s name, if any."""
    stored = batch_output_name(legacy)
    return next(
        (
            other
            for other, chosen in names.items()
            if other != identity and batch_output_name(chosen) == stored
        ),
        None,
    )


def _stored_under(
    storage_backend: "StorageBackend",
    registry: "BatchRegistryManager",
    action_name: str,
    legacy: str,
) -> bool:
    """Whether the store keeps a file under *legacy*: its output, or a batch entry."""
    if storage_backend.has_target_file(action_name, batch_output_name(legacy)):
        return True
    return registry.get_batch_job(legacy) is not None


def held_by_a_dependency(
    storage_backend: "StorageBackend | None",
    dependencies: Iterable[Any],
    action_configs: Mapping[str, Any] | None,
) -> Callable[[str], bool]:
    """Whether an action this one reads stores a file under *legacy*'s name.

    A dependency naming a version base reads each of its versions, as the executor
    expands it; the base itself stores nothing.
    """
    versions: dict[str, list[str]] = {}
    for name, config in (action_configs or {}).items():
        if isinstance(config, Mapping) and config.get("is_versioned_agent"):
            base = config.get("version_base_name")
            if base:
                versions.setdefault(base, []).append(name)
    upstream = [
        name
        for dependency in dependencies
        if isinstance(dependency, str)
        for name in versions.get(dependency, [dependency])
    ]

    def owns(legacy: str) -> bool:
        if storage_backend is None:
            return False
        stored = batch_output_name(legacy)
        return any(storage_backend.has_target_file(name, stored) for name in upstream)

    return owns


class BatchContextManager:
    """Saves and loads batch context maps via StorageBackend."""

    @staticmethod
    def _metadata_key(action_name: str, batch_name: str) -> str:
        return f"batch_context:{action_name}:{checked_batch_file_name(batch_name)}"

    @staticmethod
    def _inputs_key(action_name: str, batch_name: str) -> str:
        return f"batch_inputs:{action_name}:{checked_batch_file_name(batch_name)}"

    @staticmethod
    def save_batch_inputs(
        backend: "StorageBackend",
        action_name: str,
        source_guids: Collection[str],
        batch_name: str,
    ) -> None:
        """Record the identities this action took as input, before any narrowing.

        Separate from the context map, which holds only what was submitted: the
        disposition gate narrows the input before the map is built. Carry-forward
        needs the wider set to tell a producer that is gone from one this run did
        not answer for.
        """
        try:
            key = BatchContextManager._inputs_key(action_name, batch_name)
            backend.save_metadata(key, json.dumps(sorted(source_guids)))
            backend.delete_metadata(BatchContextManager._no_input_key(action_name, batch_name))
        except Exception as e:
            raise ProcessingError(
                f"Failed to save batch inputs: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e

    @staticmethod
    def clear_batch_inputs(backend: "StorageBackend", action_name: str, batch_name: str) -> None:
        """Remove the recording, so the next reader finds none recorded."""
        backend.delete_metadata(BatchContextManager._inputs_key(action_name, batch_name))
        backend.delete_metadata(BatchContextManager._no_input_key(action_name, batch_name))

    @staticmethod
    def _no_input_key(action_name: str, batch_name: str) -> str:
        return f"batch_no_input:{action_name}:{checked_batch_file_name(batch_name)}"

    @staticmethod
    def record_no_input(backend: "StorageBackend", action_name: str, batch_name: str) -> None:
        """Record that the file now takes no input, while its batch is still owed.

        Its own key, not an empty recording: an empty recording is what a file whose
        records carry no identity records, and is read as none recorded.
        """
        backend.save_metadata(BatchContextManager._no_input_key(action_name, batch_name), "true")

    @staticmethod
    def takes_no_input(backend: "StorageBackend", action_name: str, batch_name: str) -> bool:
        key = BatchContextManager._no_input_key(action_name, batch_name)
        return backend.load_metadata(key) is not None

    @staticmethod
    def load_batch_inputs(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> set[str] | None:
        """The input recorded for this batch, or None where none was recorded.

        A run that recorded nothing is not one that took no input, so the two are
        returned apart. Carry-forward then treats both as no evidence — read as the
        run's inputs, an empty set would leave every stored row out — but the
        distinction is the store's to report, not this function's to flatten.
        """
        key = BatchContextManager._inputs_key(action_name, batch_name)
        raw = backend.load_metadata(key)
        if raw is None:
            logger.debug("No recorded input for %s/%s", action_name, batch_name)
            return None
        # Unreadable reads as absent: raising would abandon a batch already answered,
        # and a non-list blob is refused rather than iterated — set("a1") is {"a", "1"},
        # and a wrong input set drives a rule that deletes.
        try:
            recorded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Unreadable recorded input for %s/%s — carrying every stored row instead",
                action_name,
                batch_name,
            )
            return None
        if not isinstance(recorded, list) or not all(isinstance(g, str) for g in recorded):
            logger.warning(
                "Recorded input for %s/%s is not a list of identities (%s) — "
                "carrying every stored row instead",
                action_name,
                batch_name,
                type(recorded).__name__,
            )
            return None
        return set(recorded)

    @staticmethod
    def save_batch_context_map(
        backend: "StorageBackend",
        action_name: str,
        context_map: dict[str, Any],
        batch_name: str,
    ) -> None:
        """Store the map in parts, then name them under the map's parts key.

        The parts are written first. One transaction then writes the parts key and
        deletes a map an earlier version saved whole. The parts the key named before
        are deleted last. A save that fails leaves the earlier map as it stood. A save
        that stops after the transaction leaves earlier parts that nothing reads;
        ``clear_batch_state`` (and ``--fresh``) removes them.
        """
        key = BatchContextManager._metadata_key(action_name, batch_name)
        generation = uuid.uuid4().hex[:12]
        written: list[str] = []
        try:
            earlier = _part_keys(backend, key) or []
            for index, part in enumerate(_encoded_parts(context_map)):
                part_key = _part_key(key, generation, index)
                backend.save_metadata(part_key, part)
                written.append(part_key)
            header = {"generation": generation, "parts": len(written)}
            # One transaction, so the parts key and a map saved whole exist together
            # only when an earlier version saved that map after this one saved parts.
            backend.save_and_delete_metadata({_parts_key(key): json.dumps(header)}, [key])
        except Exception as e:
            for part_key in written:
                try:
                    backend.delete_metadata(part_key)
                except Exception:
                    logger.debug("Could not delete context map part %s", part_key, exc_info=True)
            raise ProcessingError(
                f"Failed to save context map: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e
        for part_key in earlier:
            backend.delete_metadata(part_key)
        logger.debug(
            "Saved context map for %s/%s (%d entries in %d parts)",
            action_name,
            batch_name,
            len(context_map),
            len(written),
        )

    @staticmethod
    def load_batch_context_map(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> dict[str, Any]:
        """The map as saved: as one string by an earlier version, or in parts.

        A map saved whole wins over parts: a save deletes it in the transaction that
        names its parts, so both exist only when an earlier version saved it later.
        """
        try:
            key = BatchContextManager._metadata_key(action_name, batch_name)
            raw = backend.load_metadata(key)
            context_map: dict[str, Any]
            if raw is not None:
                context_map = deep_json.loads(raw)
            else:
                loaded = _loaded_parts(backend, key)
                if loaded is None:
                    raise ProcessingError(
                        f"Context map not found for {action_name}/{batch_name}",
                        context={"action_name": action_name, "batch_name": batch_name},
                    )
                context_map = loaded
            logger.debug(
                "Loaded context map for %s/%s (%d entries)",
                action_name,
                batch_name,
                len(context_map),
            )
            return context_map
        except ProcessingError:
            raise
        except json.JSONDecodeError as e:
            raise ProcessingError(
                f"Invalid JSON in context map: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e
        except Exception as e:
            raise ProcessingError(
                f"Failed to load context map: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e

    @staticmethod
    def delete_batch_context_map(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> bool:
        key = BatchContextManager._metadata_key(action_name, batch_name)
        for part_key in _part_keys(backend, key) or ():
            backend.delete_metadata(part_key)
        named = backend.delete_metadata(_parts_key(key))
        whole = backend.delete_metadata(key)  # a map an earlier version saved whole
        return named or whole


# A context map is stored in parts of about this many characters, so neither a save
# nor a load holds the whole map as one string.
_PART_CHARS = 4_000_000


def _encoded_parts(context_map: dict[str, Any]) -> Iterator[str]:
    """The map as JSON objects of about ``_PART_CHARS`` each, entries in order.

    Each entry is encoded alone and the members are joined as ``json.dumps`` joins
    them, so the parts read back into the map that one string of it reads back into.
    """
    members: list[str] = []
    size = 0
    for custom_id, entry in context_map.items():
        member = deep_json.dumps({custom_id: entry}, ensure_ascii=False)[1:-1]
        members.append(member)
        size += len(member)
        if size >= _PART_CHARS:
            yield "{" + ", ".join(members) + "}"
            members = []
            size = 0
    if members:
        yield "{" + ", ".join(members) + "}"


# checked_batch_file_name refuses a name with "#", so a file's key holds no "#" and no
# file's key is another file's part key or parts key.
def _parts_key(key: str) -> str:
    return f"{key}#parts"


def _part_key(key: str, generation: str, index: int) -> str:
    return f"{key}#{generation}:{index:06d}"


def _part_keys(backend: "StorageBackend", key: str) -> list[str] | None:
    """The keys of the parts the parts key names; None when no parts key is saved."""
    raw = backend.load_metadata(_parts_key(key))
    if raw is None:
        return None
    header = json.loads(raw)
    if not (
        isinstance(header, dict)
        and isinstance(header.get("generation"), str)
        and isinstance(header.get("parts"), int)
    ):
        raise ProcessingError(
            f"Unreadable context map parts key {_parts_key(key)}: {raw[:200]}",
            context={"key": key},
        )
    return [_part_key(key, header["generation"], index) for index in range(header["parts"])]


# A save that overtakes a load deletes the parts the load reads; the load starts again
# from the parts key this many times before it gives up.
_LOAD_TRIES = 3


def _loaded_parts(backend: "StorageBackend", key: str) -> dict[str, Any] | None:
    """The map the parts key names; None when no parts key is saved."""
    part_keys = _part_keys(backend, key)
    for _ in range(_LOAD_TRIES):
        if part_keys is None:
            return None
        context_map, missing = _joined_parts(backend, part_keys)
        if missing is None:
            return context_map
        named_now = _part_keys(backend, key)
        if named_now == part_keys:
            raise ProcessingError(
                f"Context map part {missing} is missing", context={"part": missing}
            )
        part_keys = named_now
    raise ProcessingError(
        f"Context map {key} was saved again during each of {_LOAD_TRIES} loads",
        context={"key": key},
    )


def _joined_parts(
    backend: "StorageBackend", part_keys: list[str]
) -> tuple[dict[str, Any], str | None]:
    """The map the parts hold, and the first part that is gone (None if all are there)."""
    context_map: dict[str, Any] = {}
    for part_key in part_keys:
        part = backend.load_metadata(part_key)
        if part is None:
            return {}, part_key
        context_map.update(deep_json.loads(part))
    return context_map, None
