"""Prompt preparation service for agent builder."""

from typing import Dict, Any, Optional


class PromptService:
    """Handles prompt loading and preparation for agents."""

    @staticmethod
    def debug_print_prompt(
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: str = "",
        schema: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Print prompt for debugging if enabled.

        Args:
            agent_config: Agent configuration with prompt_debug flag
            prompt_config: The prompt to display
            context_data: Context data preview (optional)
            schema: The schema being passed to the LLM (optional)
        """
        if agent_config.get("prompt_debug", False):
            divider = "=" * 50
            print(f"\n{divider}\nDEBUG MODE: Prompt being sent to the agent\n{divider}")
            print(prompt_config)

            if context_data:
                print("\n[Context Data Preview]\n" + "-" * 50)
                print(context_data)

            if schema:
                print("\n[Context Schema Preview]\n" + "-" * 50)
                import json

                print(json.dumps(schema, indent=2, ensure_ascii=False))

            print(f"{divider}\n")
