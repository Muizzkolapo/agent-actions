import re
import json
import random
import logging
from collections import Counter
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)
from agent_actions.handlers.file_handler import FileHandler


class PromptLoader:
    """
    A class for loading and validating prompts.
    """

    @staticmethod
    def extract_prompt(content: str, prompt_name: str) -> str:
        """
        Extracts a prompt from the content using the prompt_name.

        Parameters:
            content (str): The content containing the prompt.
            prompt_name (str): The name of the prompt to extract.

        Returns:
            str: The extracted prompt.

        Raises:
            ValueError: If the prompt is not found.
        """
        pattern = re.compile(rf"\{{prompt {re.escape(prompt_name)}\}}(.*?)\{{end_prompt\}}", re.DOTALL)
        match = pattern.search(content)
        if match:
            return match.group(1).strip()
        else:
            raise ValueError(f"Prompt '{prompt_name}' not found in the content.")

    @staticmethod
    def get_all_prompt_names(content: str) -> List[str]:
        """
        Extracts all prompt names from the content.

        Parameters:
            content (str): The content containing the prompts.

        Returns:
            List[str]: A list of prompt names found in the content.
        """
        pattern = re.compile(r"\{prompt\s+(\w+)\}")
        return pattern.findall(content)

    @staticmethod
    def validate_unique_prompts(filename: str, content: str) -> None:
        """
        Validates that all prompt names in the content are unique.

        Parameters:
            filename (str): The name of the file being validated.
            content (str): The content containing the prompts.

        Raises:
            ValueError: If duplicate prompt names are found.
        """
        prompt_names = PromptLoader.get_all_prompt_names(content)
        duplicates = [item for item, count in Counter(prompt_names).items() if count > 1]
        if duplicates:
            raise ValueError(f"Duplicate prompt names found in {filename}: {', '.join(duplicates)}")

    @staticmethod
    def load_prompt(prompt_name: str) -> str:
        """
        Retrieve and generate a prompt based on the prompt name provided.

        Parameters:
            prompt_name (str): The name of the prompt to load, in the format 'filename.prompt_key'.

        Returns:
            str: The loaded prompt.

        Raises:
            ValueError: If the prompt directory, file, or prompt format is invalid.
        """
        current_dir = Path.cwd()
        prompt_dir = current_dir / "prompt_store"

        if not prompt_dir.exists():
            raise ValueError("Prompt directory not found.")

        if '.' not in prompt_name:
            raise ValueError("Invalid prompt format. Expected 'filename.prompt_key'.")

        prompt_file_name, prompt_key = prompt_name.split('.', 1)
        prompt_file_str = FileHandler.find_file_in_directory(str(prompt_dir), f"{prompt_file_name}.md")
        if not prompt_file_str:
            raise ValueError(f"Prompt file '{prompt_file_name}.md' not found.")

        prompt_file_path = Path(prompt_file_str)
        content = prompt_file_path.read_text(encoding='utf-8')
        PromptLoader.validate_unique_prompts(prompt_file_path.name, content)
        return PromptLoader.extract_prompt(content, prompt_key)

    @staticmethod
    def load_few_shot_samples(few_shot_samples_path: str, agent_type: str, sample_count: int = 3) -> List[Any]:
        """
        Load random sample objects from the JSON files in the sample output directory for a specific agent type.

        Parameters:
            few_shot_samples_path (str): Base path to the sample output directory.
            agent_type (str): The type of the agent to load samples for.
            sample_count (int): Number of random sample objects to load.

        Returns:
            List[Any]: List of randomly selected sample objects.
        """
        if not few_shot_samples_path:
            logger.warning("Few shot samples path is not set; returning no samples.")
            return []

        agent_samples_path = Path(few_shot_samples_path) / agent_type
        if not agent_samples_path.exists():
            return []

        sample_files = list(agent_samples_path.glob("*.json"))
        all_samples: List[Any] = []

        for sample_file in sample_files:
            try:
                data = json.loads(sample_file.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    all_samples.extend(data)
                elif isinstance(data, dict):
                    all_samples.append(data)
            except Exception as e:
                raise ValueError(f"Error reading sample file '{sample_file}': {e}")

        if sample_count > 0 and all_samples:
            return random.sample(all_samples, min(sample_count, len(all_samples)))
        return []
