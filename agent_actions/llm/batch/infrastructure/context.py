"""Persistence of batch context maps via StorageBackend metadata store."""

import json
import logging
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
    def batch_context_exists(backend: "StorageBackend", action_name: str, batch_name: str) -> bool:
        key = BatchContextManager._metadata_key(action_name, batch_name)
        return backend.load_metadata(key) is not None

    @staticmethod
    def delete_batch_context_map(
        backend: "StorageBackend", action_name: str, batch_name: str
    ) -> bool:
        key = BatchContextManager._metadata_key(action_name, batch_name)
        return backend.delete_metadata(key)
