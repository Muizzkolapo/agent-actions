"""Module for orchestrating prompt processing workflow."""
from agent_actions.utilities.utils_processor_helpers import run_dynamic_agent
from agent_actions.core.utils.error_handling import ProcessorErrorHandlerMixin
from agent_actions.shared.exceptions import ProcessingError
from agent_actions.utilities.utils_processor_utils import ProcessorUtils
from agent_actions.preprocessing.pp_sample_enricher import SampleEnricher
from agent_actions.preprocessing.prompt_formatter import PromptFormatter
from agent_actions.preprocessing.pp_response_transformer import ResponseTransformer
from agent_actions.preprocessing.pp_context_preprocessor import ContextPreprocessor
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
            raw_prompt = PromptFormatter.get_raw_prompt(self.agent_config)
            source_content = SourcePathManager.load_source_content(source_path, context_data) if source_path else None
            if not formatted_prompt:
                formatted_prompt = PromptFormatter.format_prompt(raw_prompt, source_content, context_data)
            formatted_prompt = SampleEnricher.append_few_shot_samples(formatted_prompt, self.agent_config, self.agent_name)
            source_guid, enriched_data = ContextPreprocessor.extract_guid_and_content(context_data)
            response, executed = run_dynamic_agent(self.agent_config, self.agent_name, enriched_data, formatted_prompt, tools_path=self.agent_config.get('tools', {}).get('path'))
            if not source_guid:
                source_guid = ProcessorUtils.generate_deterministic_source_guid(enriched_data or context_data)
            if executed:
                transformed_response = ResponseTransformer.transform_response(response, enriched_data, source_guid, self.agent_config)
            else:
                transformed_response = [ProcessorUtils.create_processed_item(source_guid=source_guid, content=response)]
            idx = self.agent_config.get('idx', 0)
            for i, node in enumerate(transformed_response):
                node_id = ProcessorUtils.generate_node_id(idx)
                transformed_response[i] = ProcessorUtils.add_context_lineage_tracking(node, context_data, node_id)
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