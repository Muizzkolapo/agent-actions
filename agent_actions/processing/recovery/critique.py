"""LLM critique for stubborn validation failures.

When basic reprompting fails repeatedly, calls a separate LLM to analyze
why validation is failing and includes that analysis in the next retry prompt.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CRITIQUE_PROMPT_TEMPLATE = """The following LLM response failed validation.

## Failed Response
{response}

## Validation Errors
{errors}

Analyze why this response fails validation. What specific issues need to be fixed?
Provide a concise analysis that will help the model produce a correct response on the next attempt."""


def build_critique_prompt(response: Any, validation_errors: str) -> str:
    """Build the prompt sent to the critique LLM.

    Args:
        response: The failed LLM response.
        validation_errors: Human-readable validation error description.

    Returns:
        Formatted critique prompt string.
    """
    from .response_validator import serialize_response

    response_str = serialize_response(response)

    return CRITIQUE_PROMPT_TEMPLATE.format(
        response=response_str,
        errors=validation_errors,
    )


def format_critique_feedback(critique_response: str, standard_feedback: str) -> str:
    """Combine critique analysis with standard validation feedback.

    Critique is appended alongside the standard feedback, not replacing it.

    Args:
        critique_response: Analysis text from the critique LLM.
        standard_feedback: Standard validation feedback from build_validation_feedback().

    Returns:
        Combined feedback string.
    """
    return f"{standard_feedback}\n\n## Analysis of Failure\n{critique_response}"


def invoke_critique(agent_config: dict[str, Any], response: Any, validation_errors: str) -> str:
    """Make a critique LLM call using the action's configured provider.

    Uses the same model vendor and settings as the primary action.
    This is a synchronous call regardless of whether the main flow is batch or online.

    Args:
        agent_config: The action's agent configuration (contains model vendor, etc.).
        response: The failed LLM response to analyze.
        validation_errors: Human-readable validation error description.

    Returns:
        Critique analysis text from the LLM.

    Raises:
        Exception: Any error from the LLM call (caller should catch and handle).
    """
    from agent_actions.llm.realtime.services.invocation import ClientInvocationService

    prompt = build_critique_prompt(response, validation_errors)
    model_vendor = agent_config.get("model_vendor", "openai")
    action_name = agent_config.get("name", "unknown")

    logger.debug("[%s] Invoking critique LLM via %s", action_name, model_vendor)

    result = ClientInvocationService.invoke_client(
        model_vendor=model_vendor,
        agent_config=agent_config,
        prompt_config=prompt,
        context_data="",
        schema=None,
        granularity="record",
        action_name=f"{action_name}_critique",
    )

    if not result:
        raise ValueError("Critique LLM returned empty response")

    # Extract text from the response — providers return list[dict] or list[str]
    first = result[0]
    if isinstance(first, dict):
        return str(first.get("content", first.get("text", str(first))))
    return str(first)
