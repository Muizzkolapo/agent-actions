"""Module for orchestrating prompt processing workflow."""
from agent_actions.models import agent_builder
from agent_actions.core.utils import Utils

from ..prompt_processor.sample_enricher import SampleEnricher
from ..prompt_processor.prompt_formatter import PromptFormatter
from ..prompt_processor.response_transformer import ResponseTransformer
from ..prompt_processor.context_preprocessor import ContextPreprocessor
from agent_actions.processors.source_processor.source_path_manager import SourcePathManager

class StagingProcessor:
    """Orchestrates the prompt processing workflow (Open/Closed principle)."""
    
    def __init__(self, agent_config, agent_name):
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
            # Step 1: Enrich context with few-shot samples
            context_data = SampleEnricher.append_few_shot_samples(
                context_data, self.agent_name, self.agent_config
            )
            
            # Step 2: Get raw prompt and load source content
            raw_prompt = PromptFormatter.get_raw_prompt(self.agent_config)
            source_content = SourcePathManager.load_source_content(source_path, context_data) if source_path else None
            
            # Step 3: Format prompt if not provided
            if not formatted_prompt:
                formatted_prompt = PromptFormatter.format_prompt(raw_prompt, source_content, context_data)
            
            # Step 4: Extract guid and content if available
            guid, enriched_data = ContextPreprocessor.extract_guid_and_content(context_data)
            
            # Step 5: Apply remove_collection transformations
            prepared_context = ContextPreprocessor.prepare_context(enriched_data, self.agent_config)
            
            # Step 6: Create dynamic agent This is where tuple issue is Invalid input type:
            response = agent_builder.create_dynamic_agent(
                self.agent_config,
                self.agent_name,
                prepared_context,
                formatted_prompt,
                tools_path=self.agent_config.get('tools', {}).get('path')
            )
            
            # Step 7: Generate guid if not available
            if not guid:
                guid = Utils.generate_id()
            
            # Step 8: Transform response
            transformed_response = ResponseTransformer.transform_response(
                response, enriched_data, guid, self.agent_config
            )
            
            # Step 9: Prepare source text
            if source_path is not None and isinstance(context_data, dict) and "guid" in context_data:
                src_text = [{guid: formatted_prompt}]
            else:
                src_text = [{guid: context_data}]
            
            return transformed_response, src_text
            
        except Exception as e:
            # Propagate exceptions instead of swallowing them
            raise RuntimeError(f"Error in staging_dynamic_creator: {str(e)}") from e