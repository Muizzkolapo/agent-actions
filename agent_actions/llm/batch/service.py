"""Shared batch utilities (registry manager factory)."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


def create_registry_manager_factory(
    storage_backend: "StorageBackend",
) -> Callable[[str], BatchRegistryManager]:
    """Create a factory that creates/caches registry managers.

    Args:
        storage_backend: StorageBackend for metadata persistence.

    Returns:
        A callable that takes an ``action_name`` and returns a
        ``BatchRegistryManager`` (cached per action_name).
    """
    _cache: dict[str, BatchRegistryManager] = {}

    def get_registry_manager(action_name: str) -> BatchRegistryManager:
        if action_name not in _cache:
            _cache[action_name] = BatchRegistryManager(storage_backend, action_name)
        return _cache[action_name]

    return get_registry_manager
