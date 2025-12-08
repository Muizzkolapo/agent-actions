"""Module for orchestrating prompt processing workflow."""
from agent_actions.utilities.utils_processor_helpers import run_dynamic_agent
from agent_actions.utilities.error_handling import ProcessorErrorHandlerMixin
from agent_actions.errors import ProcessingError  # New modular pattern!
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.field_management import FieldManager
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.preprocessing.pp_response_transformer import ResponseTransformer
from agent_actions.preprocessing.context_preprocessor import ContextPreprocessor
from .source_path_manager import SourcePathManager

class StagingProcessor(ProcessorErrorHandlerMixin):
    """Orchestrates the prompt processing workflow (Open/Closed principle)."""

    def __init__(self, agent_config, agent_name):
        super().__init__()
        self.agent_config = agent_config
        self.agent_name = agent_name

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
            # Extract GUID and content first
            source_guid, enriched_data = ContextPreprocessor.extract_guid_and_content(context_data)

            # Load source content if path provided
            # For first agent (staging), source_content should be the enriched_data itself
            if source_path:
                source_content = SourcePathManager.load_source_content(source_path, context_data)
            else:
                # For staging processor, enriched_data IS the source content
                source_content = enriched_data

            # Use PromptPreparationService for consistent prompt preparation (Issue #490)
            # This ensures static data loading, context_scope, and field references work correctly
            if not formatted_prompt:
                from agent_actions.prompt_generation.prompt_preparation_service import PromptPreparationService

                prep_result = PromptPreparationService.prepare_prompt_with_context(
                    agent_config=self.agent_config,
                    agent_name=self.agent_name,
                    contents={},  # Empty for first agent (no previous outputs)
                    mode='realtime',
                    source_content=source_content  # This becomes {source.*} references
                )
                formatted_prompt = prep_result.formatted_prompt

            response, executed = run_dynamic_agent(self.agent_config, self.agent_name, enriched_data, formatted_prompt, tools_path=self.agent_config.get('tools', {}).get('path'))
            if not source_guid:
                source_guid = IDGenerator.generate_deterministic_source_guid(enriched_data or context_data)
            if executed:
                transformed_response = ResponseTransformer.transform_response(response, enriched_data, source_guid, self.agent_config)
            else:
                transformed_response = [FieldManager().create_processed_item(source_guid=source_guid, content=response)]
            idx = self.agent_config.get('idx', 0)
            for i, node in enumerate(transformed_response):
                node_id = IDGenerator.generate_node_id(idx)
                transformed_response[i] = LineageBuilder.add_context_lineage_tracking(node, context_data, node_id)
            if source_guid:
                if isinstance(enriched_data, dict) and 'chunk_info' in enriched_data:
                    original_data = {k: v for k, v in enriched_data.items() if k not in ['target_id', 'record_index', 'chunk_index']}
                    original_data['source_guid'] = source_guid
                    src_text = [original_data]
                else:
                    data_to_save = enriched_data or context_data
                    if isinstance(data_to_save, dict):
                        data_to_save = data_to_save.copy()
                        data_to_save['source_guid'] = source_guid
                    src_text = [data_to_save]
            else:
                src_text = []
            return (transformed_response, src_text)
        except Exception as e:
            self.handle_processing_error(e, 'Creating dynamic agent for prompt processing', ProcessingError, source_path=source_path, has_formatted_prompt=formatted_prompt is not None, context_type=type(context_data).__name__)