"""Prompt loading and validation from markdown files."""

import logging
import re
from collections import Counter
from pathlib import Path

from agent_actions.output.file_handler import FileHandler

logger = logging.getLogger(__name__)

# Compiled regex pattern for matching {prompt name} blocks
PROMPT_PATTERN = re.compile(r"\{prompt\s+(\w+)\}")


class PromptLoader:
    """Loads and validates prompts from markdown content."""

    @staticmethod
    def extract_prompt(content: str, prompt_name: str) -> str:
        """
        Extract a named prompt block from content.

        Raises:
            ValueError: If the prompt block is not found or unclosed.
        """
        start_token = f"{{prompt {prompt_name}}}"
        end_token = "{end_prompt}"
        start_index = content.find(start_token)
        if start_index == -1:
            raise ValueError(f"Prompt '{prompt_name}' not found in the content.")
        end_index = content.find(end_token, start_index + len(start_token))
        if end_index == -1:
            raise ValueError(f"Unclosed prompt block for '{prompt_name}'.")
        prompt_body = content[start_index + len(start_token) : end_index]
        return prompt_body.strip()

    @staticmethod
    def get_all_prompt_names(content: str) -> list[str]:
        """Return all prompt names found in the content."""
        return PROMPT_PATTERN.findall(content)

    @staticmethod
    def validate_unique_prompts(filename: str, content: str) -> None:
        """
        Raise ValueError if duplicate prompt names exist in content.
        """
        prompt_names = PromptLoader.get_all_prompt_names(content)
        duplicates = [item for item, count in Counter(prompt_names).items() if count > 1]
        if duplicates:
            raise ValueError(f"Duplicate prompt names found in {filename}: {', '.join(duplicates)}")

    @staticmethod
    def validate_prompt_blocks(filename: str, content: str) -> None:
        """Ensure every prompt block is closed with an end token."""
        for match in PROMPT_PATTERN.finditer(content):
            name = match.group(1)
            start = match.end()
            if content.find("{end_prompt}", start) == -1:
                raise ValueError(f"Unclosed prompt block for '{name}' in {filename}.")

    @staticmethod
    def load_prompt(prompt_name: str) -> str:
        """
        Load a prompt by name ('filename.prompt_key') from .md files in the project tree.

        Raises:
            ValueError: If the prompt file or prompt format is invalid.
        """
        if "." not in prompt_name:
            raise ValueError("Invalid prompt format. Expected 'filename.prompt_key'.")

        prompt_file_name, prompt_key = prompt_name.split(".", 1)
        target_filename = f"{prompt_file_name}.md"

        prompt_file_str = FileHandler.find_file_in_directory(str(Path.cwd()), target_filename)

        if not prompt_file_str:
            raise ValueError(
                f"Prompt file '{target_filename}' not found. "
                f"Searched recursively from {Path.cwd()}. "
                f"Ensure the .md file exists anywhere in your project tree."
            )

        logger.debug("Found prompt file at: %s", prompt_file_str)
        prompt_file_path = Path(prompt_file_str)
        content = prompt_file_path.read_text(encoding="utf-8")
        PromptLoader.validate_unique_prompts(prompt_file_path.name, content)
        PromptLoader.validate_prompt_blocks(prompt_file_path.name, content)
        return PromptLoader.extract_prompt(content, prompt_key)
