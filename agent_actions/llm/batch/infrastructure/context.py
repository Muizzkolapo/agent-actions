"""Persistence of batch context maps via StorageBackend metadata store."""

import json
import logging
from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Any

from agent_actions.errors import ProcessingError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchContextManager:
    """Saves and loads batch context maps via StorageBackend."""

    @staticmethod
    def _metadata_key(action_name: str, batch_name: str) -> str:
        if ".." in batch_name:
            raise ValueError(f"Invalid batch name contains path traversal: {batch_name}")
        from pathlib import Path

        safe_name = Path(batch_name).name
        return f"batch_context:{action_name}:{safe_name}"

    @staticmethod
    def _inputs_key(action_name: str, batch_name: str) -> str:
        if ".." in batch_name:
            raise ValueError(f"Invalid batch name contains path traversal: {batch_name}")
        from pathlib import Path

        safe_name = Path(batch_name).name
        return f"batch_inputs:{action_name}:{safe_name}"

    @staticmethod
    def _pool_key(action_name: str, batch_name: str) -> str:
        # Under the inputs prefix, so clearing an action's batch state clears this too.
        inputs_key = BatchContextManager._inputs_key(action_name, batch_name)
        return inputs_key.replace(f":{action_name}:", f":{action_name}:pool:", 1)

    @staticmethod
    def save_upstream_pool(
        backend: "StorageBackend", action_name: str, pool: Mapping[str, str], batch_name: str
    ) -> None:
        """Record every upstream record offered for this file, before any guard drop.

        Each identity beside its staged record. Carry-forward reads it to tell a stored
        row whose input still exists upstream from one whose input was minted again.
        """
        key = BatchContextManager._pool_key(action_name, batch_name)
        backend.save_metadata(key, json.dumps(dict(sorted(pool.items()))))

    @staticmethod
    def load_upstream_pool(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> dict[str, str] | None:
        """The recorded upstream pool, or None where none was recorded or it is unreadable."""
        raw = backend.load_metadata(BatchContextManager._pool_key(action_name, batch_name))
        if raw is None:
            return None
        try:
            recorded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(recorded, dict):
            return None
        if not all(isinstance(a, str) for a in recorded.values()):
            return None
        return recorded

    @staticmethod
    def save_batch_inputs(
        backend: "StorageBackend",
        action_name: str,
        source_guids: Collection[str] | Mapping[str, str],
        batch_name: str,
    ) -> None:
        """Record the identities this action took as input, before any narrowing.

        A mapping records each input's staged record beside it, which is what lets
        carry-forward tell a re-minted input from one that left.

        Separate from the context map, which holds only what was submitted: the
        disposition gate narrows the input before the map is built. Carry-forward
        needs the wider set to tell a producer that is gone from one this run did
        not answer for.
        """
        try:
            key = BatchContextManager._inputs_key(action_name, batch_name)
            recorded: Any = (
                dict(sorted(source_guids.items()))
                if isinstance(source_guids, Mapping)
                else sorted(source_guids)
            )
            backend.save_metadata(key, json.dumps(recorded))
        except Exception as e:
            raise ProcessingError(
                f"Failed to save batch inputs: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e

    @staticmethod
    def load_batch_inputs(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> set[str] | None:
        """The input recorded for this batch, or None where none was recorded.

        A run that recorded nothing is not one that took no input, so the two are
        returned apart. Carry-forward then treats both as no evidence — inferring
        from an empty set would supersede every stored row at once — but the
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
        if isinstance(recorded, dict) and all(isinstance(a, str) for a in recorded.values()):
            return set(recorded)
        if not isinstance(recorded, list) or not all(isinstance(g, str) for g in recorded):
            logger.warning(
                "Recorded input for %s/%s is not a recording of identities (%s) — "
                "carrying every stored row instead",
                action_name,
                batch_name,
                type(recorded).__name__,
            )
            return None
        return set(recorded)

    @staticmethod
    def load_batch_input_ancestors(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> dict[str, str] | None:
        """Each recorded input's staged record, or None where the run recorded none.

        None for a run recorded before ancestors were, or an unreadable one: carry-forward
        then falls back to the identity-only rule `load_batch_inputs` feeds.
        """
        raw = backend.load_metadata(BatchContextManager._inputs_key(action_name, batch_name))
        if raw is None:
            return None
        try:
            recorded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(recorded, dict):
            return None
        if not all(isinstance(a, str) for a in recorded.values()):
            return None
        return recorded

    @staticmethod
    def save_batch_context_map(
        backend: "StorageBackend",
        action_name: str,
        context_map: dict[str, Any],
        batch_name: str,
    ) -> None:
        try:
            key = BatchContextManager._metadata_key(action_name, batch_name)
            backend.save_metadata(key, json.dumps(context_map, ensure_ascii=False))
            logger.debug(
                "Saved context map for %s/%s (%d entries)",
                action_name,
                batch_name,
                len(context_map),
            )
        except Exception as e:
            raise ProcessingError(
                f"Failed to save context map: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e

    @staticmethod
    def load_batch_context_map(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> dict[str, Any]:
        try:
            key = BatchContextManager._metadata_key(action_name, batch_name)
            raw = backend.load_metadata(key)
            if raw is None:
                raise ProcessingError(
                    f"Context map not found for {action_name}/{batch_name}",
                    context={"action_name": action_name, "batch_name": batch_name},
                )
            context_map: dict[str, Any] = json.loads(raw)
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
        return backend.delete_metadata(key)
