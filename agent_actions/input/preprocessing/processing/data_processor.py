"""Module for processing generated data."""

from dataclasses import dataclass
from typing import Dict, List, Optional

from agent_actions.processing.helpers import transform_with_passthrough
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin
from agent_actions.errors import TransformationError
from agent_actions.config.interfaces import IDataProcessor, ProcessingMode
from agent_actions.config.di.container import registry


@dataclass
class ProcessItemRequest:
    """Request parameters for processing a single item."""

    contents: Dict
    generated_data: List[Dict]
    source_guid: str
    idx: int = 0
    passthrough_fields: Optional[Dict] = None


@registry.register_processor("data_processor")
class DataProcessor(ProcessorErrorHandlerMixin, IDataProcessor):
    """Handles post-processing of generated data (Single Responsibility)."""

    def __init__(self, agent_config: Dict):
        super().__init__()
        self.agent_config = agent_config

    def supports_async(self) -> bool:
        """Return True as this processor supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode to let system choose."""
        return ProcessingMode.AUTO

    def process_item(
        self,
        contents: Dict,
        generated_data: List[Dict],
        source_guid: str,
        passthrough_fields: Optional[Dict] = None,
    ) -> List[Dict]:
        """Process a generated data item with transformations."""
        try:
            return transform_with_passthrough(
                generated_data,
                contents,
                source_guid,
                self.agent_config,
                passthrough_fields=passthrough_fields,
            )
        except (ValueError, TypeError, KeyError) as e:
            self.handle_processing_error(
                e,
                "Processing generated data item",
                TransformationError,
                source_guid=source_guid,
                item_count=len(generated_data) if isinstance(generated_data, list) else 1,
            )
            return []
