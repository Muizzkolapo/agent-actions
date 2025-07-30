"""Module for orchestrating prompt processing workflow."""

import json
from agent_actions.common.utils.utils import run_dynamic_agent
from agent_actions.common.utils.error_handling import ProcessorErrorHandlerMixin
from agent_actions.processors.exceptions import ProcessingError
from agent_actions.core.utils import Utils
from agent_actions.common.utils.processor_utils import ProcessorUtils

from ..prompt_processor.sample_enricher import SampleEnricher
from ..prompt_processor.prompt_formatter import PromptFormatter
from ..prompt_processor.response_transformer import ResponseTransformer
from ..prompt_processor.context_preprocessor import ContextPreprocessor
from agent_actions.processors.source_processor.source_path_manager import (
    SourcePathManager,
)


class StagingProcessor(ProcessorErrorHandlerMixin):
    """Orchestrates the prompt processing workflow (Open/Closed principle)."""

    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def staging_dynamic_creator(
        self, context_data, source_path=None, formatted_prompt=None
    ):
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
            # Step 1: Get raw prompt and load source content
            raw_prompt = PromptFormatter.get_raw_prompt(self.agent_config)
            source_content = (
                SourcePathManager.load_source_content(source_path, context_data)
                if source_path
                else None
            )

            # Step 2: Format prompt if not provided
            if not formatted_prompt:
                formatted_prompt = PromptFormatter.format_prompt(
                    raw_prompt, source_content, context_data
                )

            # Step 3: Enrich prompt with few-shot samples
            formatted_prompt = SampleEnricher.append_few_shot_samples(
                formatted_prompt, self.agent_config, self.agent_name
            )

            # Step 4: Extract source_guid and content if available
            source_guid, enriched_data = ContextPreprocessor.extract_guid_and_content(
                context_data
            )

            # Step 5: Run the agent through the shared utility
            response, executed = run_dynamic_agent(
                self.agent_config,
                self.agent_name,
                enriched_data,
                formatted_prompt,
                tools_path=self.agent_config.get("tools", {}).get("path"),
            )

            # Step 7: Generate source_guid if not available
            if not source_guid:
                # Use deterministic generation based on content to ensure consistency
                source_guid = ProcessorUtils.generate_deterministic_source_guid(enriched_data or context_data)

            # Step 8: Transform response
            if executed:
                transformed_response = ResponseTransformer.transform_response(
                    response, enriched_data, source_guid, self.agent_config
                )
            else:
                # When conditional fails, preserve the original structure
                # Don't use transform_structure as it breaks down the data
                transformed_response = [ProcessorUtils.create_processed_item(
                    source_guid=source_guid,
                    content=response  # This is the original context data
                )]

            # Step 8b: Add lineage tracking (using node_id only)
            idx = self.agent_config.get('idx', 0)
            for i, node in enumerate(transformed_response):
                node_id = ProcessorUtils.generate_node_id(idx)
                transformed_response[i] = ProcessorUtils.add_context_lineage_tracking(node, context_data, node_id)


            # Step 9: Prepare source text
            if (
                source_path is not None
                and isinstance(context_data, dict)
                and "source_guid" in context_data
            ):
                src_text = [{source_guid: formatted_prompt}]
            else:
                src_text = [{source_guid: context_data}]

            return transformed_response, src_text

        except Exception as e:
            self.handle_processing_error(
                e,
                "Creating dynamic agent for prompt processing",
                ProcessingError,
                source_path=source_path,
                has_formatted_prompt=formatted_prompt is not None,
                context_type=type(context_data).__name__
            )
