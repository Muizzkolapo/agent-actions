"""Module for orchestrating prompt processing workflow."""

from agent_actions.utilities.processor.processor_helpers import (
    run_dynamic_agent,
    transform_with_passthrough,
)
from agent_actions.utilities.processor.error_handling import ProcessorErrorHandlerMixin
from agent_actions.errors import ProcessingError
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.utilities.metadata import MetadataExtractor
from agent_actions.preprocessing.context.context_preprocessor import ContextPreprocessor
from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService
from ..utilities.source_path_manager import SourcePathManager


class StagingProcessor(ProcessorErrorHandlerMixin):
    """Orchestrates the prompt processing workflow (Open/Closed principle)."""

    def __init__(self, agent_config, agent_name):
        super().__init__()
        self.agent_config = agent_config
        self.agent_name = agent_name

    def _extract_and_load_content(self, context_data, source_path):
        """Extract GUID and load source content."""
        guid_result = ContextPreprocessor.extract_guid_and_content(context_data)
        source_guid, enriched_data = guid_result

        if source_path:
            source_content = SourcePathManager.load_source_content(source_path, context_data)
        else:
            source_content = enriched_data

        return source_guid, enriched_data, source_content

    def _prepare_prompt(self, source_content, formatted_prompt):
        """Prepare the formatted prompt if not provided."""
        if formatted_prompt:
            return formatted_prompt

        prep_result = PromptPreparationService.prepare_prompt_with_context(
            agent_config=self.agent_config,
            agent_name=self.agent_name,
            contents={},
            mode="realtime",
            source_content=source_content,
        )
        return prep_result.formatted_prompt

    def _execute_agent(self, enriched_data, formatted_prompt):
        """Execute the dynamic agent and return response."""
        tools_path = self.agent_config.get("tools", {}).get("path")
        # run_dynamic_agent returns (response, executed)
        return run_dynamic_agent(
            self.agent_config,
            self.agent_name,
            enriched_data,
            formatted_prompt,
            tools_path=tools_path,
        )

    def _add_lineage_tracking(self, transformed_response, context_data):
        """Add lineage tracking and metadata to transformed response.

        Args:
            transformed_response: The response to add lineage tracking to
            context_data: The context data for lineage tracking
        """
        idx = self.agent_config.get("idx", 0)

        # Build metadata for online mode output consistency
        response_metadata = MetadataExtractor.extract_from_response(
            response=None,  # Raw response not available at this level
            agent_config=self.agent_config,
        )

        for i, node in enumerate(transformed_response):
            node_id = IDGenerator.generate_node_id(idx)
            transformed_response[i] = LineageBuilder.add_context_lineage_tracking(
                node, context_data, node_id
            )
            # Add metadata fields for consistency with batch mode
            FieldManager.add_metadata(
                transformed_response[i],
                metadata=response_metadata.to_dict(),
            )
        return transformed_response

    def _transform_response(self, response, executed, enriched_data, source_guid):
        """Transform agent response."""
        if executed:
            return transform_with_passthrough(
                response, enriched_data, source_guid, self.agent_config
            )

        return [FieldManager().create_processed_item(source_guid=source_guid, content=response)]

    def staging_dynamic_creator(self, context_data, source_path=None, formatted_prompt=None):
        """
        Create a dynamic agent for processing input documentation.

        Parameters:
            context_data (str): Documentation or input data to be processed.
            source_path (str, optional): Path to the source data file.
            formatted_prompt (str, optional): Optional formatted prompt.

        Returns:
            tuple: Transformed response and source text.
        """
        try:
            # Extract GUID and load content
            source_guid, enriched_data, source_content = self._extract_and_load_content(
                context_data, source_path
            )

            # Prepare prompt
            formatted_prompt = self._prepare_prompt(source_content, formatted_prompt)

            # Execute agent - returns (response, executed)
            response, executed = self._execute_agent(enriched_data, formatted_prompt)

            # Ensure source_guid exists
            if not source_guid:
                source_guid = IDGenerator.generate_deterministic_source_guid(
                    enriched_data or context_data
                )

            # Transform response
            transformed_response = self._transform_response(
                response, executed, enriched_data, source_guid
            )

            # Add lineage tracking
            transformed_response = self._add_lineage_tracking(
                transformed_response,
                context_data,
            )

            # Prepare source text
            src_text = self._prepare_source_text(source_guid, enriched_data, context_data)
            return (transformed_response, src_text)

        except (ValueError, TypeError, KeyError) as e:
            self.handle_processing_error(
                e,
                "Creating dynamic agent for prompt processing",
                ProcessingError,
                source_path=source_path,
                has_formatted_prompt=formatted_prompt is not None,
                context_type=type(context_data).__name__,
            )
            return None

    def _prepare_source_text(self, source_guid, enriched_data, context_data):
        """Prepare source text data for saving."""
        if not source_guid:
            return []

        if isinstance(enriched_data, dict) and "chunk_info" in enriched_data:
            excluded_keys = ["target_id", "record_index", "chunk_index"]
            original_data = {k: v for k, v in enriched_data.items() if k not in excluded_keys}
            original_data["source_guid"] = source_guid
            return [original_data]

        data_to_save = enriched_data or context_data
        if isinstance(data_to_save, dict):
            data_to_save = data_to_save.copy()
            data_to_save["source_guid"] = source_guid
        return [data_to_save]
