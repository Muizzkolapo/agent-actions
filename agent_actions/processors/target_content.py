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
from agent_actions.logging_setup import setup_logging
logger = setup_logging()
logger = logging.getLogger(__name__)

class TargetContentProcessor:
    def __init__(self, agent_config, agent_name):
        """
        Initialize the TargetContentProcessor with the given agent configuration and agent name.
        
        :param agent_config: Configuration details for the agent.
        :param agent_name: Name of the agent being processed.
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

    def process(self, data, file_path):
        """
        Process the given data using the agent configuration and source data from the file path.
        
        :param data: List of items to process.
        :param file_path: Path to the source data file.
        :return: List of processed items.
        """
        try:
            source_data = self._load_source_data(file_path)
            processed_data = []

            for items in data:
                try:
                    processed_item = self._process_single_item(items, source_data)
                    processed_data.extend(processed_item)
                except Exception as e:
                    logger.error(f"Error processing item: {e}")

            return processed_data
        except Exception as e:
            logger.error(f"Error in process_data: {e}")
            raise

    def process_for_side_output(self, data, file_path):
        """
        Process the data and segregate main output and side output based on the configuration.
        
        :param data: List of items to process.
        :param file_path: Path to the source data file.
        :return: Tuple of (main_output, side_output).
        """
        try:
            source_data = self._load_source_data(file_path)
            main_output, side_output = [], []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    if isinstance(processed_item, list):
                        for sub_item in processed_item:
                            if isinstance(sub_item.get('content', {}), dict) and sub_item['content'].get('side_output', False):
                                side_output.append(sub_item)
                            else:
                                main_output.append(sub_item)
                    else:
                        logger.warning(f"Unexpected item format: {processed_item}")
                except Exception as e:
                    logger.error(f"Error processing item: {e}")

            return main_output, side_output
        except Exception as e:
            logger.error(f"Error in process_data_for_side_output: {e}")
            raise

    def _process_single_item(self, item, source_data):
        """
        Process a single item using the source data and agent configuration.
        
        :param item: Item to process.
        :param source_data: Loaded source data corresponding to the item.
        :return: Processed item as a list of transformed objects.
        """
        contents, guid = item['content'], item['guid']
        source_content = DataTransformer.get_content_by_guid(source_data, guid)
        generated_data = self._generate_data(contents, source_content)
        return self._process_item(contents, generated_data, guid)

    def _load_source_data(self, file_path):
        """
        Load source data from the file corresponding to the provided path.
        
        :param file_path: Path to the source data file.
        :return: Loaded source data as a dictionary.
        """
        try:
            source_path = Path(file_path).parents[2] / "source" / os.path.basename(file_path)
            with open(source_path, 'r') as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Error loading source data from {file_path}: {e}")
            raise

    def _generate_data(self, contents, source_content):
        """
        Generate data using the appropriate method based on the agent configuration.
        
        :param contents: Content of the current item being processed.
        :param source_content: Content from the source data corresponding to the current item.
        :return: Generated data based on the provided contents and source content.
        """
        self._add_few_shot_samples(contents)
        return self._create_agent_with_data(contents, source_content)

    def _add_few_shot_samples(self, contents):
        """
        Add few-shot samples to the contents if specified in the configuration.
        
        :param contents: Content of the current item being processed.
        """
        sample_count = self._parse_sample_count()
        if sample_count > 0:
            try:
                _, _, few_shot_samples_path = FileHandler.get_agent_paths(self.agent_name)
                samples = AgentManager.load_few_shot_samples(few_shot_samples_path, self.agent_config['agent_type'], sample_count)
                if isinstance(contents, dict):
                    contents['samples'] = samples
                else:
                    logger.warning("Contents is not a dictionary. Cannot add samples.")
            except FileNotFoundError as e:
                logger.error(f"Few-shot samples path not found: {e}")
        else:
            logger.debug("No few-shot samples loaded.")

    def _parse_sample_count(self):
        """
        Parse and validate the sample count from the agent configuration.
        
        :return: Sample count as an integer.
        """
        try:
            return int(self.agent_config.get("use_few_shot_samples", 0))
        except ValueError:
            logger.warning("Invalid value for 'use_few_shot_samples'. Defaulting to 0.")
            return 0

    def _create_agent_with_data(self, contents, source_content):
        """
        Create a dynamic agent with the prepared data.
        
        :param contents: Content of the current item being processed.
        :param source_content: Content from the source data corresponding to the current item.
        :return: Generated agent with prepared data.
        """
        try:
            if not isinstance(contents, dict):
                contents = {"data": contents}

            raw_prompt = self.agent_config.get('prompt', '')
            if raw_prompt.startswith('$'):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])

            formatted_prompt = StringProcessor.replace_guid_placeholder(raw_prompt or "Process the following content: {content}", str(source_content))
            formatted_prompt = StringProcessor.replace_placeholders(formatted_prompt, contents)
            
            return agent_builder.create_dynamic_agent(self.agent_config, self.agent_name, contents, formatted_prompt)
        except Exception as e:
            logger.error(f"Error in _create_agent_with_data: {e}")
            raise

    def _process_item(self, contents, generated_data, guid):
        """
        Process a single item and return the transformed response.
        
        :param contents: Original content of the current item.
        :param generated_data: Generated data based on the provided contents.
        :param guid: GUID of the current item.
        :return: Transformed item as a structured response.
        """
        if ConfigValidator.should_update_schema(self.agent_config, [self.agent_config['agent_type']], {self.agent_config['agent_type']: []}):
            updated_data = [DataTransformer.update_schema_objects(contents, data, []) for data in generated_data]
            return DataTransformer.transform_structure([{guid: updated_data}])
        else:
            return DataTransformer.transform_structure([{guid: generated_data}])
