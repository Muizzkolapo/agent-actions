import os
import re
import traceback
from collections import Counter
from agent_actions.handlers.file_handler import FileHandler

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
            str: The extracted prompt or "Prompt not found."
        """
        # Regular expression to match the prompt block
        pattern = re.compile(rf"\{{prompt {re.escape(prompt_name)}\}}(.*?)\{{end_prompt\}}", re.DOTALL)

        # Search for the prompt using the pattern
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            return "Prompt not found."

    @staticmethod
    def get_all_prompt_names(content):
        """
        Extracts all prompt names from the content.

        Parameters:
            content (str): The content containing the prompts.

        Returns:
            list: A list of prompt names found in the content.
        """
        # Regular expression to find all prompt names
        pattern = re.compile(r"\{prompt\s+(\w+)\}")
        return pattern.findall(content)

    @staticmethod
    def validate_unique_prompts(filename,content):
        """
        Validates that all prompt names in the content are unique.

        Parameters:
            content (str): The content containing the prompts.
            filename (str): The name of the file being validated.

        Raises:
            ValueError: If duplicate prompt names are found.
        """
        prompt_names = PromptLoader.get_all_prompt_names(content)
        duplicates = [item for item, count in Counter(prompt_names).items() if count > 1]
        if duplicates:
            raise ValueError(f"Duplicate prompt names found in {filename}: {', '.join(duplicates)}")

    @staticmethod
    def load_prompt(prompt_name):
        """
        Retrieve and generate a prompt based on the prompt name provided.

        Parameters:
            prompt_name (str): The name of the prompt to load, in the format 'filename.prompt_key'.

        Returns:
            str: The loaded prompt as a string.
        """
        try:
            current_dir = os.getcwd()
            prompt_dir = os.path.join(current_dir, "prompt_store")

            if not os.path.exists(prompt_dir):
                raise FileNotFoundError("Prompt directory not found.")

            # Extract the prompt file name and the prompt key
            prompt_file_name, prompt_key = prompt_name.split('.', 1)

            # Search for the file in the prompt directory
            prompt_file_path = FileHandler.find_file_in_directory(prompt_dir, f"{prompt_file_name}.md")

            if not prompt_file_path:
                raise FileNotFoundError(f"Prompt file not found: {prompt_file_name}.md")

            # Read the content of the prompt file
            with open(prompt_file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            # Get the filename from the path
            filename = os.path.basename(prompt_file_path)

            # Validate that prompt names are unique
            PromptLoader.validate_unique_prompts(content, filename)

            prompt_data = PromptLoader.extract_prompt(content, prompt_key)

            return prompt_data

        except Exception as e:
            print(f"An error occurred in load_prompt: {e}")
            traceback.print_exc()
            return None
