"""Module for staging data loading and processing."""
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
from agent_actions.exceptions import (
    raise_source_content_error,
    raise_few_shot_sample_error,
    raise_prompt_error,
    raise_content_processing_error
)

class PromptProcessor:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name

    def _append_few_shot_samples(self, context_data):
        """Append few shot samples to the input documentation if configured."""
        _, _, few_shot_samples_path = FileHandler.get_agent_paths(self.agent_name)
        sample_count = self.agent_config.get("use_few_shot_samples", 0)
        try:
            sample_count = int(sample_count)
        except ValueError:
            raise_few_shot_sample_error(sample_count)

        if sample_count > 0:
            samples = AgentManager.load_few_shot_samples(
                few_shot_samples_path,
                agent_type=self.agent_config['agent_type'],
                sample_count=sample_count
            )
            samples_str = "\n\n".join(json.dumps(sample, indent=2) for sample in samples)

            if isinstance(context_data, dict):
                context_data = json.dumps(context_data, indent=2)
            context_data += "\n\nfew shot samples:\n" + samples_str

        return context_data

    def _get_raw_prompt(self):
        """Retrieve and process the raw prompt from the agent configuration."""
        raw_prompt = self.agent_config.get('prompt', '')
        if isinstance(raw_prompt, str) and raw_prompt.startswith('$'):
            raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
        if not raw_prompt:
            raise_prompt_error()
        return raw_prompt

    def _load_source_content(self, source_path, context_data):
        """Load source content based on the input documentation's GUID."""
        try:
            with open(source_path, 'r') as file:
                source_data = json.load(file)
                if isinstance(context_data, dict) and "guid" in context_data:
                    guid = context_data["guid"]
                    for item in source_data:
                        if guid in item:
                            return item[guid]
        except Exception as e:
            raise_source_content_error(source_path, str(e))
        return None

class StagingContentLoader:
    def __init__(self, agent_config, agent_name):
        self.agent_config = agent_config
        self.agent_name = agent_name
        self.staging_processor = PromptProcessor(agent_config, agent_name)

    def process(self, content, file_type, file_path=None):
        try:
            if file_type in ['.txt', '.md', '.pdf', '.docx', '.html']:
                return self._process_chunks(content)
            elif file_type == '.json':
                return self._process_json_content(content, file_path)
            elif file_type in ('.csv', '.xlsx'):
                return self._process_tabular_content(content)
            elif file_type == '.xml':
                return self._process_xml_content(content)
            else:
                raise_content_processing_error(file_type, "Unsupported file type")
        except Exception as e:
            raise_content_processing_error(file_type, str(e))

