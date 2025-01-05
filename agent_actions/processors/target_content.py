"""Module for target content processing."""
import os
import json
from pathlib import Path
from agent_actions.models import agent_builder
from agent_actions.core.utils import Utils
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.transformers.data_transformer import DataTransformer
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.handlers.prompt_handler import PromptLoader
from abc import ABC, abstractmethod
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.exceptions import (
    raise_source_data_load_error,
    raise_few_shot_sample_parse_error,
    raise_few_shot_sample_path_error,
    raise_content_type_error,
    raise_item_processing_error,
    raise_content_processing_error,
    raise_side_output_processing_error,
    raise_unexpected_format_error,
    raise_agent_creation_error,
)

class ContentProcessor(ABC):
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    @abstractmethod
    def process(self, data, file_path):
        pass

    @abstractmethod
    def process_for_side_output(self, data, file_path):
        pass

class SourceDataLoader:
    def __init__(self, agent_name):
        self.agent_name = agent_name

    def load_source_data(self, file_path):
        try:
            source_path = Path(file_path).parents[2] / "source" / os.path.basename(file_path)
            with open(source_path, 'r') as file:
                return json.load(file)
        except Exception as e:
            raise_source_data_load_error(file_path, str(e))

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
                samples = PromptLoader.load_few_shot_samples(
                    few_shot_samples_path,
                    self.agent_config['agent_type'],
                    sample_count
                )
                if isinstance(contents, dict):
                    contents['samples'] = samples
                else:
                    raise_content_type_error()
            except FileNotFoundError as e:
                raise_few_shot_sample_path_error(str(e))

    def _parse_sample_count(self):
        try:
            return int(self.agent_config.get("use_few_shot_samples", 0))
        except ValueError as e:
            raise_few_shot_sample_parse_error(self.agent_config.get("use_few_shot_samples"))

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
            raise_agent_creation_error(str(e))

class DataProcessor:
    def __init__(self, agent_config):
        self.agent_config = agent_config

    def process_item(self, contents, generated_data, guid):
        side_collection = self.agent_config.get('side_collection', [])
        remove_collection = self.agent_config.get('remove_collection', [])
        
        if side_collection:
            updated_data = [
                DataTransformer.update_schema_objects(contents, data, side_collection)
                for data in generated_data
            ]
            return DataTransformer.transform_structure([{guid: updated_data}])
        elif remove_collection:
            updated_data = [
                DataTransformer.remove_schema_objects(data, remove_collection)
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
                    raise_item_processing_error(items.get('guid', 'unknown'), str(e))

            return processed_data
        except Exception as e:
            raise_content_processing_error(str(e))

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
                        raise_unexpected_format_error(str(processed_item))
                except Exception as e:
                    raise_item_processing_error(item.get('guid', 'unknown'), str(e))

            return main_output, side_output
        except Exception as e:
            raise_side_output_processing_error(str(e))

    def _process_single_item(self, item, source_data):
        try:
            contents, guid = item['content'], item['guid']
            source_content = DataTransformer.get_content_by_guid(source_data, guid)
            self.sample_manager.add_few_shot_samples(contents)

            conditional_clause = self.agent_config.get('conditional_clause', '').lower()
            if conditional_clause:
                if execute_user_defined_function(conditional_clause, contents):
                    generated_data = self.data_generator.create_agent_with_data(contents, source_content)
                    return self.data_processor.process_item(contents, generated_data, guid)
                else:
                    return self.data_processor.process_item(contents, [contents], guid)
            else:
                generated_data = self.data_generator.create_agent_with_data(contents, source_content)
                return self.data_processor.process_item(contents, generated_data, guid)
        except Exception as e:
            raise_item_processing_error(guid, str(e))

    def process_file_level(self, data):
        try:
            contents, guid = data[0]['content'], data[0]['guid']
            generated_data = self.data_generator.create_agent_with_data(data)
            return self.data_processor.process_item(contents, generated_data, guid)
        except Exception as e:
            raise_content_processing_error(str(e))
