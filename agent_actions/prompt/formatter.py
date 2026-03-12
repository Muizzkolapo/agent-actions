"""Prompt formatting and loading."""

from agent_actions.errors import PromptValidationError
from agent_actions.prompt.handler import PromptLoader
from agent_actions.utils.constants import PROMPT_KEY


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
            raise PromptValidationError(
                f"Failed to get raw prompt: {str(e)}",
                context={
                    "field": "raw_prompt",
                    "agent_config": str(agent_config),
                    "operation": "get_raw_prompt",
                },
                cause=e,
            ) from e
