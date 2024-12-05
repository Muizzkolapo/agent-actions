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
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.logging_setup import setup_logging
from abc import ABC, abstractmethod

logger = setup_logging()
logger = logging.getLogger(__name__)

# Abstract Base Class
class ContentProcessor(ABC):
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.logger = logging.getLogger(f'agent_actions.processors.{self.__class__.__name__}')

    @abstractmethod
    def process(self, data, file_path):
        pass

    @abstractmethod
    def process_for_side_output(self, data, file_path):
        pass

# Source Data Loader
class SourceDataLoader:
    def __init__(self, agent_name):
        self.agent_name = agent_name

    def load_source_data(self, file_path):
        try:
            source_path = Path(file_path).parents[2] / "source" / os.path.basename(file_path)
            with open(source_path, 'r') as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Error loading source data from {file_path}: {e}")
            raise

# Few-Shot Sample Manager
class FewShotSampleManager:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def add_few_shot_samples(self, contents):
        sample_count = self._parse_sample_count()
        if sample_count > 0:
            try:
                _, _, few_shot_samples_path = FileHandler.get_agent_paths(self.agent_name)
                samples = AgentManager.load_few_shot_samples(
                    few_shot_samples_path,
                    self.agent_config['agent_type'],
                    sample_count
                )
                if isinstance(contents, dict):
                    contents['samples'] = samples
                else:
                    logger.warning("Contents is not a dictionary. Cannot add samples.")
            except FileNotFoundError as e:
                logger.error(f"Few-shot samples path not found: {e}")
        else:
            logger.debug("No few-shot samples loaded.")

    def _parse_sample_count(self):
        try:
            return int(self.agent_config.get("use_few_shot_samples", 0))
        except ValueError:
            logger.warning("Invalid value for 'use_few_shot_samples'. Defaulting to 0.")
            return 0

class DataGenerator:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def create_agent_with_data(self, contents, source_content=None):
        try:
            if not isinstance(contents, dict):
                contents = {"data": contents}

            raw_prompt = self.agent_config.get('prompt', '')
            if raw_prompt.startswith('$'):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])

            formatted_prompt = StringProcessor.replace_guid_placeholder(
                raw_prompt or "Process the following content: {content}",
                str(source_content)
            )
            formatted_prompt = StringProcessor.replace_placeholders(formatted_prompt, contents)

            return agent_builder.create_dynamic_agent(
                self.agent_config,
                self.agent_name,
                contents,
                formatted_prompt
            )
        except Exception as e:
            logger.error(f"Error in create_agent_with_data: {e}")
            raise

class DataProcessor:
    def __init__(self, agent_config):
        self.agent_config = agent_config

    def process_item(self, contents, generated_data, guid):
        side_collection = self.agent_config.get('side_collection', [])
        
        if side_collection:
            updated_data = [
                DataTransformer.update_schema_objects(contents, data, side_collection)
                for data in generated_data
            ]
            return DataTransformer.transform_structure([{guid: updated_data}])
        else:
            return DataTransformer.transform_structure([{guid: generated_data}])

class TargetContentProcessor(ContentProcessor):
    def __init__(self, agent_config, agent_name):
        super().__init__(agent_config, agent_name)
        self.source_loader = SourceDataLoader(agent_name)
        self.sample_manager = FewShotSampleManager(agent_config, agent_name)
        self.data_generator = DataGenerator(agent_config, agent_name)
        self.data_processor = DataProcessor(agent_config)

    def process(self, data, file_path):
        try:
            source_data = self.source_loader.load_source_data(file_path)
            processed_data = []

            for items in data:
                try:
                    processed_item = self._process_single_item(items, source_data)
                    processed_data.extend(processed_item)
                except Exception as e:
                    logger.error(f"Error processing item: {e}")

            return processed_data
        except Exception as e:
            logger.error(f"Error in process: {e}")
            raise

    def process_for_side_output(self, data, file_path):
        try:
            source_data = self.source_loader.load_source_data(file_path)
            main_output, side_output = [], []

            for item in data:
                try:
                    processed_item = self._process_single_item(item, source_data)
                    if isinstance(processed_item, list):
                        for sub_item in processed_item:
                            content = sub_item.get('content', {})
                            if isinstance(content, dict) and content.get('side_output', False):
                                side_output.append(sub_item)
                            else:
                                main_output.append(sub_item)
                    else:
                        logger.warning(f"Unexpected item format: {processed_item}")
                except Exception as e:
                    logger.error(f"Error processing item: {e}")

            return main_output, side_output
        except Exception as e:
            logger.error(f"Error in process_for_side_output: {e}")
            raise

    def _process_single_item(self, item, source_data):
        contents, guid = item['content'], item['guid']
        source_content = DataTransformer.get_content_by_guid(source_data, guid)
        self.sample_manager.add_few_shot_samples(contents)
        generated_data = self.data_generator.create_agent_with_data(contents, source_content)
        return self.data_processor.process_item(contents, generated_data, guid)

    def process_file_level(self, data):

        try:
            generated_data = self.data_generator.create_agent_with_data(data)

            return generated_data
        except Exception as e:
            logger.error(f"Error in process_file_level: {e}")
            raise
