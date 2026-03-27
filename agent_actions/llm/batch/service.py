"""Shared batch utilities (registry manager factory)."""

import logging
from collections.abc import Callable
from pathlib import Path

from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

logger = logging.getLogger(__name__)


def create_registry_manager_factory() -> Callable[[str], BatchRegistryManager]:
    """Create a factory that creates/caches registry managers."""
    _cache: dict[str, BatchRegistryManager] = {}

    def get_registry_manager(output_directory: str) -> BatchRegistryManager:
        if output_directory not in _cache:
            _cache[output_directory] = BatchRegistryManager(
                Path(output_directory) / "batch" / ".batch_registry.json"
            )
        return _cache[output_directory]

    return get_registry_manager
