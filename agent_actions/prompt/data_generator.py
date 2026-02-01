"""Module for generating data using agents.

This module uses RecordProcessor for unified processing with retry support.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING

from agent_actions.output.response.config_types import AgentEntryDict

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.config.interfaces import IGenerator, ProcessingMode
from agent_actions.config.di.container import registry
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode as CoreProcessingMode,
    ProcessingStatus,
)
from agent_actions.errors import GenerationError

logger = logging.getLogger(__name__)


@registry.register_generator("data_generator")
class DataGenerator(IGenerator):
    """
    Handles agent creation and data generation.

    Uses RecordProcessor internally for unified processing with retry support.
    """

    def __init__(
        self,
        agent_config: AgentEntryDict,
        agent_name: str,
        dependency_configs: Optional[Dict[str, AgentEntryDict]] = None,
        agent_indices: Optional[Dict[str, int]] = None,
        storage_backend: Optional["StorageBackend"] = None,
    ):
        """
        Initialize the data generator.

        Args:
            agent_config: Configuration for the agent
            agent_name: Name of the agent
            dependency_configs: Optional dict mapping dependency names to their configs.
                              Used to build namespaced field_context for {agent.field} references.
            agent_indices: Optional dict mapping agent names to their node indices.
                         Used for loading historical node data via {action_name.field} references.
            storage_backend: Optional storage backend for historical data loading.
        """
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.dependency_configs = dependency_configs or {}
        self.agent_indices = agent_indices or {}
        self.storage_backend = storage_backend

        # Create RecordProcessor for unified processing with retry
        self._record_processor = RecordProcessor(
            agent_config=self.agent_config,
            agent_name=self.agent_name,
        )

    def supports_async(self) -> bool:
        """Return True as this generator supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def create_agent_with_data(
        self,
        contents: Any,
        source_content: Optional[Any] = None,
        loop_context: Optional[Dict] = None,
        workflow_metadata: Optional[Dict] = None,
        current_item: Optional[Dict] = None,
        file_path: Optional[str] = None,
    ) -> Tuple[List[Dict], bool, Dict]:
        """
        Create an agent with the provided data and generate results.

        Uses RecordProcessor internally for unified processing with retry support.

        Args:
            contents: Content to process
            source_content: Optional source content for prompt formatting
            loop_context: Optional loop context for {loop.*} references
            workflow_metadata: Optional workflow metadata for {workflow.*} references
            current_item: Optional current item dict containing lineage and
                source_guid for historical node loading
            file_path: Optional file path for constructing historical node paths

        Returns:
            Tuple containing:
            - generated data (List[Dict])
            - flag indicating if agent was executed (bool)
            - passthrough_fields extracted from field_context (Dict)

        Raises:
            GenerationError: If agent creation or data generation fails
        """
        try:
            # Build processing context for subsequent-stage processing
            context = ProcessingContext(
                agent_config=self.agent_config,
                agent_name=self.agent_name,
                mode=CoreProcessingMode.ONLINE,
                is_first_stage=False,  # This is subsequent-stage processing
                source_data=source_content,
                file_path=file_path,
                loop_context=loop_context,
                workflow_metadata=workflow_metadata,
                agent_indices=self.agent_indices,
                dependency_configs=self.dependency_configs,
                storage_backend=self.storage_backend,
            )

            # Build item in expected format for RecordProcessor
            # RecordProcessor expects {content, source_guid} for subsequent-stage
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

            # Process via RecordProcessor (has retry support)
            result = self._record_processor.process(item, context)

            # Convert ProcessingResult to legacy tuple format
            if result.status == ProcessingStatus.FILTERED:
                return (None, False, {})
            elif result.status == ProcessingStatus.SKIPPED:
                return (contents, False, result.passthrough_fields)
            elif result.status == ProcessingStatus.EXHAUSTED:
                # Retry exhausted - return as failed but with recovery metadata
                logger.warning(
                    "Processing exhausted for '%s': %s",
                    self.agent_name,
                    result.error,
                )
                return (None, False, result.passthrough_fields)
            elif result.status == ProcessingStatus.FAILED:
                raise GenerationError(f"Processing failed: {result.error}")
            else:
                # SUCCESS
                return (result.data, True, result.passthrough_fields)

        except GenerationError:
            raise
        except Exception as e:
            raise GenerationError(f"Failed to create agent with data: {str(e)}", cause=e) from e
