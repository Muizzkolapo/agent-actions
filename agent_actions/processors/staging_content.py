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
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.logging_setup import setup_logging
logger = setup_logging()

logger = logging.getLogger(__name__)

class PromptProcessor:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.logger = logging.getLogger('agent_actions.processors.staging_content')

    def staging_dynamic_creator(self, input_documentation, source_path=None, formatted_prompt=None):
        """
        Create a dynamic agent for processing input documentation.

        Parameters:
            input_documentation (str): Documentation or input data to be processed.
            source_path (str, optional): Path to the source data file.
            formatted_prompt (str, optional): Optional formatted prompt.

        Returns:
            tuple: Transformed response and source text.
        """
        input_documentation = self._append_few_shot_samples(input_documentation)
        raw_prompt = self._get_raw_prompt()
        source_content = self._load_source_content(source_path, input_documentation) if source_path else None
        formatted_prompt = self._format_prompt(raw_prompt, source_content, input_documentation)
        if source_path is not None and isinstance(input_documentation, dict) and "guid" in input_documentation and "content" in input_documentation:
            guid = input_documentation["guid"]
            input_documentation_new = input_documentation["content"]
            response = agent_builder.create_dynamic_agent(
                self.agent_config,
                self.agent_name,
                input_documentation_new,
                formatted_prompt
            )
            transformed_response_temp = [{guid: response}]
            transformed_response = DataTransformer.transform_structure(transformed_response_temp)
            src_text = [{guid: formatted_prompt}]
        else:
            response = agent_builder.create_dynamic_agent(
                self.agent_config,
                self.agent_name,
                input_documentation,
                formatted_prompt
            )
            guid = Utils.generate_id() if not isinstance(input_documentation, dict) or "guid" not in input_documentation else input_documentation["guid"]
            transformed_response_temp = [{guid: response}]
            transformed_response = DataTransformer.transform_structure(transformed_response_temp)
            src_text = [{guid: input_documentation}]

        return transformed_response, src_text

    def _append_few_shot_samples(self, input_documentation):
        """Append few shot samples to the input documentation if configured."""
        _, _, few_shot_samples_path = FileHandler.get_agent_paths(self.agent_name)
        sample_count = self.agent_config.get("use_few_shot_samples", 0)
        try:
            sample_count = int(sample_count)
        except ValueError:
            self.logger.warning("use_few_shot_samples is not an integer. Defaulting to 0.")
            sample_count = 0

        if sample_count > 0:
            self.logger.debug(f"Loading {sample_count} few shot samples.")
            samples = AgentManager.load_few_shot_samples(
                few_shot_samples_path,
                agent_type=self.agent_config['agent_type'],
                sample_count=sample_count
            )
            samples_str = "\n\n".join(json.dumps(sample, indent=2) for sample in samples)

            if isinstance(input_documentation, dict):
                input_documentation = json.dumps(input_documentation, indent=2)
            input_documentation += "\n\nfew shot samples:\n" + samples_str
        else:
            self.logger.info("Not using few shot samples.")

        return input_documentation

    def _get_raw_prompt(self):
        """Retrieve and process the raw prompt from the agent configuration."""
        raw_prompt = self.agent_config.get('prompt', '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            self.logger.warning("No prompt found in agent_config. Using default prompt.")
            raw_prompt = "Process the following content: {content}"
        return raw_prompt

    def _format_prompt(self, raw_prompt, source_content, input_documentation):
        """Replace placeholders in the raw prompt with source content and input documentation."""
        source_loaded_prompt = StringProcessor.replace_guid_placeholder(raw_prompt, str(source_content))
        formatted_prompt = StringProcessor.replace_placeholders(source_loaded_prompt, input_documentation)
        return formatted_prompt

    def _load_source_content(self, source_path, input_documentation):
        """Load source content based on the input documentation's GUID."""
        try:
            with open(source_path, 'r') as file:
                source_data = json.load(file)
                if isinstance(input_documentation, dict) and "guid" in input_documentation:
                    guid = input_documentation["guid"]
                    for item in source_data:
                        if guid in item:
                            return item[guid]
        except Exception as e:
            self.logger.error(f"Error loading source content: {e}")
        return None


class StagingContentLoader:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.staging_processor = PromptProcessor(agent_config, agent_name)
    def process(self, content, file_type, file_path=None):
        if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
            return self._process_chunks(content)
        elif file_type == '.json':
            return self._process_json_content(content, file_path)
        elif file_type in ('.csv', '.xlsx'):
            return self._process_tabular_content(content)
        elif file_type == '.xml':
            return self._process_xml_content(content)

    def _process_chunks(self, chunks):
        """
        Process the given chunks and create dynamic agents for each chunk.

        Args:
            chunks (list): A list of text chunks.
            agent_config (dict): The configuration for the dynamic agents.
            agent_name (str): The name of the dynamic agents.

        Returns:
            list: A list of dynamic agents created from the chunks.
        """
        data_chunk = []
        src_text = []
        for input_documentation in chunks:
            dynamic_agent, src_collection = self.staging_processor.staging_dynamic_creator(
                input_documentation)
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)
        return data_chunk, src_text

    def _process_json_content(self, content, file_path):
        """
        Process JSON content and create dynamic agents for each value in the content.

        Args:
            content (list or dict): The JSON content to be processed.
            agent_config (dict): The configuration for the dynamic agents.
            agent_name (str): The name of the dynamic agents.

        Returns:
            list: A list of dynamic agents created from the JSON content.
        """
        data_chunk = []
        src_text = []
        src_legacy_path = FileHandler.get_file_info(file_path)
        
        if isinstance(content, list):
            for obj in content:
                dynamic_agent,src_collection = self.staging_processor.staging_dynamic_creator(input_documentation=obj,source_path=src_legacy_path)
                data_chunk.extend(dynamic_agent)
                src_text.extend(src_collection)
    
        elif isinstance(content, dict):
            for value in content.values():
                if isinstance(value, list):
                    for obj in value:
                        dynamic_agent,src_collection = self.staging_processor.staging_dynamic_creator(input_documentation=obj,source_path=src_legacy_path)
                        data_chunk.extend(dynamic_agent)
                        src_text.extend(src_collection)
                else:
                    generated_content,src_collection  = self.staging_processor.staging_dynamic_creator(input_documentation=content,source_path=src_legacy_path)
                    data_chunk.extend(generated_content)
                    src_text.extend(src_collection)
        
        return data_chunk,src_text

    def _process_tabular_content(self, content):
        """
        Process tabular content and create dynamic agents for each row in the content.

        Args:
            content (list): The tabular content to be processed.
            agent_config (dict): The configuration for the dynamic agents.
            agent_name (str): The name of the dynamic agents.

        Returns:
            list: A list of dynamic agents created from the tabular content.
        """
        data_chunk = []
        src_text = []
        
        for row in content:
            dynamic_agent,src_collection = self.staging_processor.staging_dynamic_creator(row)
            data_chunk.extend(dynamic_agent)
            src_text.extend(src_collection)
        
        return data_chunk,src_text

    def _process_xml_content(self, content):
        """
        Process XML content and create dynamic agents for each element in the content.

        Args:
            content (tuple): The XML content to be processed.
            agent_config (dict): The configuration for the dynamic agents.
            agent_name (str): The name of the dynamic agents.

        Returns:
            list: A list of dynamic agents created from the XML content.
        """
        data_chunk = []
        src_text = []
        _, root = content
        for element in root.findall('.//*'):
            if list(element):
                chunk_output,src_collection = self.staging_processor.staging_dynamic_creator(self.process_xml_element(element))
                data_chunk.extend(chunk_output)
                src_text.extend(src_collection)
        return data_chunk,src_text

