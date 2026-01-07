"""
Module for prompt formatting and loading.
"""

from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.utilities.constants import PROMPT_KEY
from agent_actions.prompt_generation.prompt_utils import PromptUtils


class PromptFormatter:
    """Handles prompt formatting and loading (Single Responsibility)."""

    @staticmethod
    def get_raw_prompt(agent_config):
        """
        Retrieve and process the raw prompt from the agent configuration.

        Parameters:
            agent_config: Configuration containing prompt information

        Returns:
            Raw prompt string

        Raises:
            ValueError: If prompt retrieval fails
        """
        try:
            raw_prompt = agent_config.get(PROMPT_KEY, "")
            if isinstance(raw_prompt, str) and raw_prompt.startswith("$"):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
            if not raw_prompt:
                raw_prompt = "Process the following content: {content}"
            return raw_prompt
        except Exception as e:
            from agent_actions.errors import PromptValidationError  # New modular pattern!

            raise PromptValidationError(
                f"Failed to get raw prompt: {str(e)}",
                context={
                    "field": "raw_prompt",
                    "agent_config": str(agent_config),
                    "operation": "get_raw_prompt",
                },
                cause=e,
            ) from e

    @staticmethod
    def format_prompt(raw_prompt, field_context=None):
        """
        Replace {reference.field} patterns in the prompt.

        Parameters:
            raw_prompt: Template prompt with field references
            field_context: Dict with field references (source, agent outputs, loop, workflow)

        Returns:
            Formatted prompt with all {reference.field} patterns replaced

        Raises:
            ValueError: If prompt formatting fails
        """
        try:
            if field_context:
                return PromptUtils.replace_field_references(raw_prompt, field_context)
            return raw_prompt
        except Exception as e:
            from agent_actions.errors import PromptValidationError  # New modular pattern!

            raise PromptValidationError(
                f"Failed to format prompt: {str(e)}",
                context={
                    "field": "formatted_prompt",
                    "raw_prompt": str(raw_prompt)[:100],
                    "operation": "format_prompt",
                },
                cause=e,
            ) from e
