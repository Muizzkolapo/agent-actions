"""Prompt preparation service for agent builder."""

import json
import logging
from typing import Any

import click

logger = logging.getLogger(__name__)


class PromptService:
    """Handles prompt loading and preparation for agents."""

    @staticmethod
    def debug_print_prompt(
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: str = "",
        schema: dict[str, Any] | None = None,
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
            lines = [f"\n{divider}\nDEBUG MODE: Prompt being sent to the agent\n{divider}"]
            lines.append(prompt_config)

            if context_data:
                lines.append("\n[Context Data Preview]\n" + "-" * 50)
                lines.append(context_data)

            if schema:
                lines.append("\n[Context Schema Preview]\n" + "-" * 50)
                lines.append(json.dumps(schema, indent=2, ensure_ascii=False))

            lines.append(f"{divider}\n")
            # One write, so the blocks of actions running in parallel do not interleave.
            click.echo("\n".join(lines))
            logger.debug(
                "prompt_debug output displayed for agent %s", agent_config.get("name", "unknown")
            )
