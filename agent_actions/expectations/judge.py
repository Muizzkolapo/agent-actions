"""LLM-judged expectations: prompt, invocation, and verdict parsing.

Mirrors `processing/recovery/critique.py`'s auxiliary-LLM-call pattern —
same ad-hoc invocation entry point, same default of reusing the generating
action's own model, same plain-text-JSON verdict instead of a vendor-native
structured-output schema.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

JUDGE_PROMPT_TEMPLATE = """Judge whether the value below satisfies the rule. Read the rule \
carefully — it defines exactly what counts as passing.

## Rule
{rule}
{context_section}
## Value under test
{value}

Respond with ONLY a JSON object, no other text:
{{"passed": true, "reason": "one sentence"}} or {{"passed": false, "reason": "one sentence"}}"""


def build_judge_prompt(rule: str, value: Any, context: dict[str, Any] | None) -> str:
    """Render the prompt sent to the judge LLM."""
    context_section = ""
    if context:
        lines = "\n".join(f"- {name}: {content}" for name, content in context.items())
        context_section = f"\n## Grounding context\n{lines}\n"
    rendered_value = value if isinstance(value, str) else json.dumps(value, default=str)
    return JUDGE_PROMPT_TEMPLATE.format(
        rule=rule, context_section=context_section, value=rendered_value
    )


def invoke_judge(
    agent_config: dict[str, Any],
    rule: str,
    value: Any,
    *,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    action_name: str = "unknown",
) -> tuple[bool, str]:
    """Ask the judge LLM whether *value* satisfies *rule*.

    Raises whatever `ClientInvocationService.invoke_client` raises — network,
    auth, and provider errors are the caller's to handle, exactly like
    `invoke_critique`. A malformed judge response (not JSON, no boolean
    `passed` key) is this function's own call to make: it is always a
    failure, never a silent pass.
    """
    from agent_actions.llm.realtime.services.invocation import ClientInvocationService

    model_vendor = agent_config.get("model_vendor")
    if not model_vendor:
        raise ValueError("agent_config missing required 'model_vendor' for judge LLM call")

    effective_config = agent_config if model is None else {**agent_config, "model_name": model}
    prompt = build_judge_prompt(rule, value, context)

    result = ClientInvocationService.invoke_client(
        model_vendor=model_vendor,
        agent_config=effective_config,
        prompt_config=prompt,
        context_data="",
        schema=None,
        granularity="record",
        action_name=f"{action_name}_judge",
    )
    if not result:
        return False, "judge call returned an empty response"

    first = result[0]
    text = (
        str(first.get("content", first.get("text", str(first))))
        if isinstance(first, dict)
        else str(first)
    )

    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return False, f"judge response was not valid JSON: {text[:200]!r}"

    if not isinstance(parsed, dict) or not isinstance(parsed.get("passed"), bool):
        return False, f"judge response missing a boolean 'passed' key: {text[:200]!r}"

    return parsed["passed"], str(parsed.get("reason", ""))


def invoke_judge_with_votes(
    agent_config: dict[str, Any],
    rule: str,
    value: Any,
    *,
    votes: int = 1,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    action_name: str = "unknown",
) -> tuple[bool, str]:
    """Run the judge `votes` times independently and take the majority.

    A tie fails closed: `passed_count * 2 > votes` is a strict majority, so
    an even split never counts as a pass.
    """
    if votes <= 1:
        return invoke_judge(
            agent_config, rule, value, context=context, model=model, action_name=action_name
        )

    def one_vote(_: int) -> tuple[bool, str]:
        return invoke_judge(
            agent_config, rule, value, context=context, model=model, action_name=action_name
        )

    with ThreadPoolExecutor(max_workers=votes) as pool:
        results = list(pool.map(one_vote, range(votes)))

    passed_count = sum(1 for passed, _ in results if passed)
    majority = passed_count * 2 > votes
    if majority:
        return True, f"{passed_count}/{votes} judge votes passed"

    dissents = "; ".join(detail for passed, detail in results if not passed)
    return False, f"{passed_count}/{votes} judge votes passed: {dissents}"


def _llm_judge_unreachable(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    raise NotImplementedError(
        "llm_judge is dispatched by the runner's judge caller, not registry.check"
    )
