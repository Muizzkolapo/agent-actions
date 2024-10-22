"""Module for staging data loading and processing."""
import os
import json
import logging
from pathlib import Path
from agent_actions.models import agent_builder
from agent_actions.core.utils import Utils
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.handlers.agent_handlers import PromptLoader


logger = logging.getLogger(__name__)
class TargetContentProcessor:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def process(self, data, file_path):
        try:
            source_data = self._load_source_data(file_path)
            processed_data = []
            side_collection = self.agent_config.get('side_collection', [])
            selection_keys = [self.agent_config['agent_type']]

            for items in data:
                try:
                    processed_item = self._process_single_item(items, source_data, side_collection, selection_keys)
                    processed_data.extend(processed_item)
                except Exception as e:
                    logger.error(f"Error processing item: {e}")

            return processed_data
        except Exception as e:
            logger.error(f"Error in process_data: {e}")
            raise

    def process_for_side_output(self, data, file_path):

        try:
            source_data = self._load_source_data(file_path)
            main_output = []
            side_output = []
            side_collection = self.agent_config.get('side_collection', [])
            selection_keys = [self.agent_config['agent_type']]

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data, side_collection, selection_keys)
                    if isinstance(processed_item, list):
                        for sub_item in processed_item:
                            content = sub_item.get('content', {})
                            if isinstance(content, dict):
                                if content.get('side_output', False):
                                    side_output.append(sub_item)
                                else:
                                    main_output.append(sub_item)
                            else:
                                logger.warning(f"Unexpected content format: {content}")
                    else:
                        logger.warning(f"Unexpected item format: {processed_item}")
                except Exception as e:
                    logger.error(f"Error processing item: {str(e)}")

            return main_output, side_output
        except Exception as e:
            logger.error(f"Error in process_data_for_side_output: {str(e)}")
            raise

    def _process_single_item(self, item, source_data, side_collection, selection_keys):
        contents = item['content']
        guid = item['guid']
        source_content = DataTransformer.get_content_by_guid(source_data, guid)

        generated_data = self._generate_data(contents, source_content)
        return self._process_item(contents, generated_data, guid, side_collection, selection_keys)

    def _load_source_data(self, file_path):
        """Load source data from the corresponding file."""
        file_name = os.path.basename(file_path)
        path = Path(file_path)
        base_path = path.parents[2]
        source_path = os.path.join(base_path, "source", file_name)
        with open(source_path, 'r') as file:
            return json.load(file)

    def _generate_data(self, contents, source_content):
        """Generate data using the appropriate method based on the agent configuration."""
        self._add_few_shot_samples(contents)
        return self._create_agent_with_data(contents, source_content)

    def _add_few_shot_samples(self, contents):
        """Add few-shot samples to the contents if specified in the configuration."""
        sample_count = self._parse_sample_count()
        
        try:
            _, _, few_shot_samples_path = FileHandler.get_agent_paths(self.agent_name)
        except FileNotFoundError as e:
            logger.error(f"Error finding sample output path: {e}")
            return

        if sample_count > 0:
            logger.info(f"Loading {sample_count} few shot samples for agent type {self.agent_config['agent_type']}.")
            samples = AgentManager.load_few_shot_samples(few_shot_samples_path, self.agent_config['agent_type'], sample_count)
            if isinstance(contents, dict):
                contents['samples'] = samples
            else:
                logger.warning("Contents is not a dictionary. Cannot add samples.")
        else:
            logger.info("Not using few shot samples.")

    def _parse_sample_count(self):
        """Parse and validate the sample count from the agent configuration."""
        sample_count = self.agent_config.get("use_few_shot_samples", 0)
        try:
            return int(sample_count)
        except ValueError:
            logger.warning("use_few_shot_samples is not an integer. Defaulting to 0.")
            return 0

    def _create_agent_with_data(self, contents, source_content):
        """Create a dynamic agent with the prepared data."""
        try:
            logger.info(f"Entering _create_agent_with_data method")
            logger.info(f"Contents type: {type(contents)}")
            logger.info(f"Model vendor: {self.agent_config.get('model_vendor', 'Not specified')}")

            if not isinstance(contents, dict):
                logger.warning(f"Expected contents to be a dict, but got {type(contents)}")
                contents = {"data": contents}  # Wrapping non-dict content in a dict

            if self.agent_config['model_vendor'].lower() == 'tool':
                logger.info(f"Creating dynamic agent with tool: {self.agent_name}")
                return agent_builder.create_dynamic_agent(self.agent_config, self.agent_name, contents)
            else:
                logger.info(f"Creating dynamic agent with model: {self.agent_config['model_vendor']}")
                raw_prompt = self.agent_config.get('prompt', '')
                if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
                    raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])  
                if not raw_prompt:
                    logger.warning("No prompt found in agent_config. Using default prompt.")
                    raw_prompt = "Process the following content: {content}"

                logger.info("Preparing formatted prompt")
                source_loaded_prompt = StringProcessor.replace_guid_placeholder(raw_prompt, str(source_content))
                formatted_prompt = StringProcessor.replace_placeholders(source_loaded_prompt, contents)
                
                logger.info("Calling create_dynamic_agent with formatted prompt")
                return agent_builder.create_dynamic_agent(self.agent_config, self.agent_name, contents, formatted_prompt)
        except Exception as e:
            logger.error(f"Error in _create_agent_with_data: {str(e)}")
            logger.exception("Full traceback:")
            raise  

    def _process_item(self, contents, generated_data, guid, side_collection, selection_keys):
        """Process a single item and return the transformed response."""
        if ConfigValidator.should_update_schema(self.agent_config, selection_keys, {self.agent_config['agent_type']: side_collection}):
            updated_generated_data = [
                DataTransformer.update_schema_objects(contents, data_item, side_collection)
                for data_item in generated_data
            ]
            response_temp = [{guid: updated_generated_data}]
        else:
            response_temp = [{guid: generated_data}]

        return DataTransformer.transform_structure(response_temp)


