"""Persistence of batch context maps via StorageBackend metadata store."""

import json
import logging
from collections.abc import Collection
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

        None rather than an empty set: the reader infers rows away from this, so
        "nothing recorded" and "recorded as empty" must not read alike. A batch
        submitted before the input was recorded returns None and is left alone.
        """
        key = BatchContextManager._inputs_key(action_name, batch_name)
        raw = backend.load_metadata(key)
        if raw is None:
            logger.debug("No recorded input for %s/%s", action_name, batch_name)
            return None
        try:
            return set(json.loads(raw))
        except (json.JSONDecodeError, TypeError) as e:
            raise ProcessingError(
                f"Invalid JSON in batch inputs: {e}",
                cause=e,
                context={"action_name": action_name, "batch_name": batch_name},
            ) from e

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
