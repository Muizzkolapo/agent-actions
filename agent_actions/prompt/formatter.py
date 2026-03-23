"""Prompt formatting and loading."""

from agent_actions.errors import ConfigValidationError, PromptValidationError
from agent_actions.logging.filters import _redact_sensitive_data
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
            ConfigValidationError: If prompt is an empty/whitespace string for non-tool/hitl/seed actions
            PromptValidationError: If prompt retrieval or loading fails
        """
        raw_prompt = agent_config.get(PROMPT_KEY)
        if agent_config.get("kind") not in ("tool", "hitl", "seed", "source") and isinstance(raw_prompt, str) and not raw_prompt.strip():
            raise ConfigValidationError(
                f"prompt cannot be an empty string for action '{agent_config.get('agent_type', 'unknown')}'"
            )
        try:
            if PROMPT_KEY not in agent_config:
                return "Process the following content: {content}"
            if isinstance(raw_prompt, str) and raw_prompt.startswith("$"):
                raw_prompt = PromptLoader.load_prompt(raw_prompt[1:])
            if not raw_prompt:
                return "Process the following content: {content}"
            return raw_prompt
        except Exception as e:
            raise PromptValidationError(
                f"Failed to get raw prompt: {str(e)}",
                context={
                    "field": "raw_prompt",
                    "agent_config": str(_redact_sensitive_data(agent_config)),
                    "operation": "get_raw_prompt",
                },
                cause=e,
            ) from e
