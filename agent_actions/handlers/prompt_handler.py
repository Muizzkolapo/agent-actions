import traceback
import os 
from agent_actions.handlers.file_handler import FileHandler
import re


class PromptLoader:
    """
    A class for loading prompts.
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
        pattern = re.compile(rf"\{{prompt {prompt_name}\}}(.*?)\{{end_prompt\}}", re.DOTALL)

        # Search for the prompt using the pattern
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            return "Prompt not found."

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

            prompt_data = PromptLoader.extract_prompt(content, prompt_key)

            return prompt_data

        except Exception as e:
            print(f"An error occurred in load_prompt: {e}")
            traceback.print_exc()
            return None