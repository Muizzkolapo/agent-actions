"""Prompt preparation service for agent builder."""

from typing import Dict, Any, Optional
from agent_actions.preprocessing.prompt_formatter import PromptFormatter


class PromptService:
    """Handles prompt loading and preparation for agents."""

    @staticmethod
    def prepare_prompt(
        agent_config: Dict[str, Any],
        formatted_prompt: Optional[str]
    ) -> str:
        """
        Return an actual prompt string.

        Either returns the pre-formatted prompt or loads the prompt from disk
        using the unified formatter.

        Args:
            agent_config: Agent configuration containing prompt settings
            formatted_prompt: Pre-formatted prompt string (optional)

        Returns:
            Prepared prompt string
        """
        if formatted_prompt is not None:
            return formatted_prompt

        # Load and validate prompt using unified formatter (Phase 3: Issue #492)
        return PromptFormatter.get_raw_prompt(agent_config)

    @staticmethod
    def debug_print_prompt(
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: str = ''
    ) -> None:
        """
        Print prompt for debugging if enabled.

        Args:
            agent_config: Agent configuration with prompt_debug flag
            prompt_config: The prompt to display
            context_data: Context data preview (optional)
        """
        if agent_config.get('prompt_debug', False):
            divider = '=' * 50
            print(f'\n{divider}\nDEBUG MODE: Prompt being sent to the agent\n{divider}')
            print(prompt_config)

            if context_data:
                print('\n[Context Data Preview]\n' + '-' * 50)
                print(context_data)

            print(f'{divider}\n')
