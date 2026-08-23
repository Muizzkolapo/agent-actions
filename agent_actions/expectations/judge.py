"""LLM-judged expectations: prompt, invocation, and verdict parsing.

Mirrors `processing/recovery/critique.py`'s auxiliary-LLM-call pattern — same
ad-hoc invocation entry point, same default of reusing the generating action's
own model, same plain-text-JSON verdict instead of a vendor-native
structured-output schema.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent_actions.expectations.types import Expectation
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.utils.json_parsing import strip_code_fences

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


def _read_verdict(text: str) -> dict[str, Any] | None:
    """The reply as a verdict object, or None when it is not one.

    Both readers consume the whole reply or refuse, which is the point: the
    judge prompt shows the model the exact object to emit, so a reply that
    merely quotes that example while arguing the opposite must not be mistaken
    for a verdict.
    """
    candidate = strip_code_fences(text).strip()
    for reader in (json.loads, ast.literal_eval):
        try:
            parsed = reader(candidate)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


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
    `invoke_critique`. A reply that cannot be read as a verdict (no object, no
    boolean `passed` key) is this function's own call to make: it is always a
    failure, never a silent pass.
    """
    from agent_actions.llm.realtime.services.invocation import ClientInvocationService

    model_vendor = agent_config.get("model_vendor")
    if not model_vendor:
        raise ValueError("agent_config missing required 'model_vendor' for judge LLM call")

    # json_mode: False so the provider hands back the model's text rather than
    # parsing it through the best-effort reader, which would scavenge a verdict
    # out of prose before `_read_verdict` ever saw the reply.
    effective_config = {**agent_config, "json_mode": False}
    if model is not None:
        effective_config["model_name"] = model
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

    payload = ResponseBuilder.unwrap(result, effective_config)
    parsed = payload if isinstance(payload, dict) else _read_verdict(str(payload))
    if parsed is None:
        return False, f"judge response was not a verdict object: {str(payload)[:200]!r}"

    if not isinstance(parsed.get("passed"), bool):
        return False, f"judge response missing a boolean 'passed' key: {str(payload)[:200]!r}"

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


def _content_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def cache_key(expectation: Expectation, value: Any) -> tuple[str, str, str, str | None]:
    """The `(id, definition hash, field content hash, model)` verdict-cache key."""
    return (
        expectation.resolved_id,
        expectation.definition_hash(),
        _content_hash(value),
        expectation.params.get("model"),
    )


class CachedJudge:
    """Caches judge verdicts for one action across every record it processes.

    `lookup` and `call_and_cache` are separate on purpose — the budget check
    (a later task) has to run between a cache miss and the LLM call that follows it.
    """

    def __init__(self, agent_config: dict[str, Any], action_name: str = "unknown") -> None:
        self._agent_config = agent_config
        self._action_name = action_name
        self._cache: dict[tuple[str, str, str, str | None], tuple[bool, str]] = {}

    def lookup(self, expectation: Expectation, value: Any) -> tuple[bool, str] | None:
        return self._cache.get(cache_key(expectation, value))

    def call_and_cache(
        self, expectation: Expectation, value: Any, context: dict[str, Any] | None = None
    ) -> tuple[bool, str]:
        params = expectation.params
        verdict = invoke_judge_with_votes(
            self._agent_config,
            params["rule"],
            value,
            votes=params.get("votes", 1),
            context=context,
            model=params.get("model"),
            action_name=self._action_name,
        )
        self._cache[cache_key(expectation, value)] = verdict
        return verdict


class JudgeBudget:
    """Caps how many real judge calls one action's ExpectationService may make this run.

    `max_calls=None` is uncapped — the budget is opt-in, not a default limit.
    """

    def __init__(self, max_calls: int | None) -> None:
        self._remaining = max_calls

    def try_acquire(self) -> bool:
        if self._remaining is None:
            return True
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True

    @property
    def remaining(self) -> int | None:
        return self._remaining


def _llm_judge_unreachable(value: Any, params: dict[str, Any]) -> tuple[bool, str]:
    raise NotImplementedError(
        "llm_judge is dispatched by the runner's judge caller, not registry.check"
    )
