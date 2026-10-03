"""Persistence of batch context maps via StorageBackend metadata store."""

import json
import logging
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from agent_actions.errors import ProcessingError

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def batch_output_name(file_name: str) -> str:
    """The name a batch's output file is stored under, given the input file it answers.

    Finalize writes under it and submission looks stored rows up under it; two copies of
    this rule would let one drift and every carried input read as having no stored row.
    """
    from pathlib import Path

    return f"{Path(file_name).stem}.json"


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
