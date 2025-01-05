import os
import re
import json 
import random
from collections import Counter
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.exceptions import (
    raise_duplicate_prompt_error,
    raise_prompt_not_found_error,
    raise_prompt_directory_error,
    raise_prompt_file_not_found_error
)

class PromptLoader:
    """
    A class for loading and validating prompts.
    """

    @staticmethod
    def extract_prompt(content, prompt_name):
        """
        Extracts a prompt from the content using the prompt_name.

        Parameters:
            content (str): The content containing the prompt.
            prompt_name (str): The name of the prompt to extract.

        Returns:
            str: The extracted prompt.

        Raises:
            PromptNotFoundError: If the prompt is not found in the content.
        """
        pattern = re.compile(rf"\{{prompt {re.escape(prompt_name)}\}}(.*?)\{{end_prompt\}}", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            raise_prompt_not_found_error(prompt_name)

    @staticmethod
    def get_all_prompt_names(content):
        """
        Extracts all prompt names from the content.

        Parameters:
            content (str): The content containing the prompts.

        Returns:
            list: A list of prompt names found in the content.
        """
        pattern = re.compile(r"\{prompt\s+(\w+)\}")
        return pattern.findall(content)

    @staticmethod
    def validate_unique_prompts(filename, content):
        """
        Validates that all prompt names in the content are unique.

        Parameters:
            content (str): The content containing the prompts.
            filename (str): The name of the file being validated.

        Raises:
            DuplicatePromptError: If duplicate prompt names are found.
        """
        prompt_names = PromptLoader.get_all_prompt_names(content)
        duplicates = [item for item, count in Counter(prompt_names).items() if count > 1]
        if duplicates:
            raise_duplicate_prompt_error(filename, duplicates)

    @staticmethod
    def load_prompt(prompt_name):
        """
        Retrieve and generate a prompt based on the prompt name provided.

        Parameters:
            prompt_name (str): The name of the prompt to load, in the format 'filename.prompt_key'.

        Returns:
            str: The loaded prompt.

        Raises:
            PromptDirectoryError: If the prompt directory is not found.
            PromptFileNotFoundError: If the prompt file is not found.
            PromptNotFoundError: If the prompt is not found in the file.
        """
        try:
            current_dir = os.getcwd()
            prompt_dir = os.path.join(current_dir, "prompt_store")

            if not os.path.exists(prompt_dir):
                raise_prompt_directory_error()

            prompt_file_name, prompt_key = prompt_name.split('.', 1)
            prompt_file_path = FileHandler.find_file_in_directory(prompt_dir, f"{prompt_file_name}.md")

            if not prompt_file_path:
                raise_prompt_file_not_found_error(f"{prompt_file_name}.md")

            with open(prompt_file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            filename = os.path.basename(prompt_file_path)
            PromptLoader.validate_unique_prompts(filename, content)

            return PromptLoader.extract_prompt(content, prompt_key)

        except Exception as e:
            raise e

    @staticmethod
    def load_few_shot_samples(few_shot_samples_path, agent_type, sample_count=3):
        """
        Load random sample objects from the JSON files in the sample output directory for a specific agent type.

        Parameters:
            few_shot_samples_path (str): Base path to the sample output directory.
            agent_type (str): The type of the agent to load samples for.
            sample_count (int): Number of random sample objects to load.

        Returns:
            list: List of randomly selected sample objects.
        """

        agent_samples_path = os.path.join(few_shot_samples_path, agent_type)
        if not os.path.exists(agent_samples_path):
            return []

        sample_files = [f for f in os.listdir(agent_samples_path) if f.endswith('.json')]
        all_samples = []

        for sample_file in sample_files:
            with open(os.path.join(agent_samples_path, sample_file), 'r') as file:
                data = json.load(file)
                if isinstance(data, list):
                    all_samples.extend(data)
                elif isinstance(data, dict):
                    all_samples.append(data)

        if sample_count > 0 and all_samples:
            selected_samples = random.sample(all_samples, min(sample_count, len(all_samples)))
        else:
            selected_samples = []
        return selected_samples