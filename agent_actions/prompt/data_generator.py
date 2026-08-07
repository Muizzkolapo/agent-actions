"""Data generation using agents with OnlineLLMStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import ActionEntryDict

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.config.interfaces import IGenerator
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

logger = logging.getLogger(__name__)


class DataGenerator(IGenerator):
    """Handles agent creation and data generation via OnlineLLMStrategy."""

    def __init__(
        self,
        agent_config: ActionEntryDict,
        agent_name: str,
        dependency_configs: dict[str, ActionEntryDict] | None = None,
        agent_indices: dict[str, int] | None = None,
        storage_backend: StorageBackend | None = None,
    ):
        """Initialize the data generator with agent config and optional dependency info."""
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.dependency_configs = dependency_configs or {}
        self.agent_indices = agent_indices or {}
        self.storage_backend = storage_backend

        self._online_strategy = OnlineLLMStrategy(
            agent_config=cast(dict[str, Any], self.agent_config),
            agent_name=self.agent_name,
        )
        self._enrichment_pipeline = EnrichmentPipeline()
