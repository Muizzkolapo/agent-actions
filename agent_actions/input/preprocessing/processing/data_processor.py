"""Post-processing of generated data with passthrough transformations."""

from dataclasses import dataclass

from agent_actions.config.di.container import registry
from agent_actions.config.interfaces import IDataProcessor, ProcessingMode
from agent_actions.errors import TransformationError
from agent_actions.processing.error_handling import ProcessorErrorHandlerMixin
from agent_actions.processing.helpers import transform_with_passthrough


@dataclass
class ProcessItemRequest:
    """Request parameters for processing a single item."""

    contents: dict
    generated_data: list[dict]
    source_guid: str
    passthrough_fields: dict | None = None


@registry.register_processor("data_processor")
class DataProcessor(ProcessorErrorHandlerMixin, IDataProcessor):
    """Handles post-processing of generated data (Single Responsibility)."""

    def __init__(self, agent_config: dict):
        super().__init__()
        self.agent_config = agent_config

    def supports_async(self) -> bool:
        """Return whether this processor supports async operations."""
        return True

    def get_processing_mode(self) -> ProcessingMode:
        """Return AUTO processing mode."""
        return ProcessingMode.AUTO

    def process_item(
        self,
        contents: dict,
        generated_data: list[dict],
        source_guid: str,
        passthrough_fields: dict | None = None,
    ) -> list[dict]:
        """Process a generated data item with transformations."""
        try:
            return transform_with_passthrough(
                generated_data,
                contents,
                source_guid,
                self.agent_config,
                action_name=self.agent_config.get("name", "unknown_action"),
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
