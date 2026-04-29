"""Data generation using agents with OnlineLLMStrategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import ActionConfigDict, ActionEntryDict

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.config.di.container import registry
from agent_actions.config.interfaces import IGenerator, ProcessingMode
from agent_actions.config.types import RunMode
from agent_actions.errors import GenerationError
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingStatus,
)

logger = logging.getLogger(__name__)


@registry.register_generator("data_generator")
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

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def create_agent_with_data(
        self,
        contents: Any,
        source_content: Any | None = None,
        version_context: dict | None = None,
        workflow_metadata: dict | None = None,
        current_item: dict | None = None,
        file_path: str | None = None,
    ) -> tuple[list[dict], bool, dict]:
        """
        Create an agent with the provided data and generate results.

        Returns:
            Tuple of (generated data, was_executed flag, passthrough_fields).

        Raises:
            GenerationError: If agent creation or data generation fails.
        """
        try:
            context = ProcessingContext(
                agent_config=cast(ActionConfigDict, self.agent_config),
                agent_name=self.agent_name,
                mode=RunMode.ONLINE,
                is_first_stage=False,  # This is subsequent-stage processing
                source_data=source_content if isinstance(source_content, list) else [],
                file_path=file_path,
                version_context=version_context,
                workflow_metadata=workflow_metadata,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                storage_backend=self.storage_backend,
            )

            if current_item is not None:
                item = current_item
            elif isinstance(contents, dict):
                item = {
                    "content": contents,
                    "source_guid": contents.get("source_guid"),
                    "lineage": contents.get("lineage", []),
                    "target_id": contents.get("target_id"),
                }
            else:
                item = {"content": contents}

            result = self._online_strategy.process_record(item, context, skip_guard=False)
            if result.status not in (ProcessingStatus.DEFERRED, ProcessingStatus.FILTERED):
                result = self._enrichment_pipeline.enrich(result, context)

            if result.status == ProcessingStatus.FILTERED:
                return ([], False, {})
            elif result.status == ProcessingStatus.SKIPPED:
                return (contents, False, result.passthrough_fields)
            elif result.status == ProcessingStatus.EXHAUSTED:
                logger.warning(
                    "Processing exhausted for '%s': %s",
                    self.agent_name,
                    result.error,
                )
                return ([], False, result.passthrough_fields)
            elif result.status == ProcessingStatus.UNPROCESSED:
                return (result.data, False, result.passthrough_fields)
            elif result.status == ProcessingStatus.FAILED:
                raise GenerationError(
                    f"Processing failed for action '{self.agent_name}': {result.error}"
                )
            else:
                # SUCCESS
                return (result.data, True, result.passthrough_fields)

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(
                f"Failed to create agent '{self.agent_name}' with data: {str(e)}", cause=e
            ) from e
