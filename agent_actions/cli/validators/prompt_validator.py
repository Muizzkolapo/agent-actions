"""
Prompt validation utilities.
"""

from pathlib import Path
from agent_actions.handlers.prompt_handler import PromptLoader


class PromptValidator:
    """Handles prompt validation operations."""
    
    @staticmethod
    def validate_prompts(prompt_dir: Path) -> None:
        """
        Validate that all prompts in the prompt store directory are unique.

        Args:
            prompt_dir: Path to the prompt_store directory.
        """
        if not prompt_dir.exists():
            return

        for prompt_file in prompt_dir.iterdir():
            if prompt_file.suffix == '.md':
                content = prompt_file.read_text(encoding='utf-8')
                PromptLoader.validate_unique_prompts(prompt_file.name, content)