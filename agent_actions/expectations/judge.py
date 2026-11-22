"""LLM-judged expectations: prompt, verdict parsing, cache and budget.

The judge is a requester of side calls (`agent_actions.llm.side_calls`): a rule's
question about a value becomes a `SideCall` (`judge_call`), and the replies its
copies return become the verdict (`verdict_from_replies`). Whether the call runs
now or goes out in a batch is the executor's business, not this module's.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import threading
from typing import Any

from agent_actions.expectations.types import Expectation
from agent_actions.llm.side_calls import OnlineSideCalls, SideCall, SideCallExecutor, SideReplies
from agent_actions.utils.json_parsing import strip_code_fences

logger = logging.getLogger(__name__)

# The judge's kind of side call; a batch run names its judge batches by it.
JUDGE_KIND = "judge"

# Where a batch run hands the result writer what its judge batches left: the verdicts
# they returned ("verdicts") and the judge budget still unspent ("budget_remaining").
BATCH_JUDGE_KEY = "_batch_judge"

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


def verdict_from_reply(payload: Any) -> tuple[bool, str]:
    """One judge reply read as a verdict; a reply that is not one is always a failure."""
    parsed = payload if isinstance(payload, dict) else _read_verdict(str(payload))
    if parsed is None:
        return False, f"judge response was not a verdict object: {str(payload)[:200]!r}"

    if not isinstance(parsed.get("passed"), bool):
        return False, f"judge response missing a boolean 'passed' key: {str(payload)[:200]!r}"

    return parsed["passed"], str(parsed.get("reason", ""))


def judge_call(
    rule: str,
    value: Any,
    *,
    key: str,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    votes: int = 1,
) -> SideCall:
    """The side call that asks whether *value* satisfies *rule*, one copy per vote."""
    return SideCall(
        kind=JUDGE_KIND,
        key=key,
        prompt=build_judge_prompt(rule, value, context),
        model=model,
        copies=max(int(votes), 1),
    )


def call_failed(error: Any) -> str:
    """The detail of a judgement whose call failed: always a failure, never a silent pass."""
    return f"judge call failed: {error}"


def verdict_from_replies(replies: SideReplies) -> tuple[bool, str]:
    """The verdict of one judge call, from what its votes replied.

    A reply that cannot be read as a verdict (no object, no boolean `passed` key),
    or a vote that answered nothing, is a failed vote.
    """
    if replies.error is not None:
        return False, call_failed(replies.error)
    return tally_votes(
        [
            (False, "judge call returned an empty response")
            if reply is None
            else verdict_from_reply(reply)
            for reply in replies.replies
        ]
    )


def tally_votes(results: list[tuple[bool, str]]) -> tuple[bool, str]:
    """The verdict of independent votes on one value: a strict majority passes.

    A single vote is its own verdict.
    """
    if len(results) == 1:
        return results[0]
    votes = len(results)
    passed_count = sum(1 for passed, _ in results if passed)
    majority = passed_count * 2 > votes
    if majority:
        return True, f"{passed_count}/{votes} judge votes passed"

    dissents = "; ".join(detail for passed, detail in results if not passed)
    return False, f"{passed_count}/{votes} judge votes passed: {dissents}"


def _content_hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


CacheKey = tuple[str, str, str, str | None]


def cache_key(expectation: Expectation, value: Any) -> CacheKey:
    """The `(id, definition hash, field content hash, model)` verdict-cache key."""
    return (
        expectation.resolved_id,
        expectation.definition_hash(),
        _content_hash(value),
        expectation.params.get("model"),
    )


def verdict_key(key: CacheKey) -> str:
    """A cache key as text, the form a batch run persists a verdict under between passes."""
    return json.dumps(list(key))


# What a held-back call answers until its batch returns; the pass that sees it defers.
_AWAITING_BATCH = (False, "awaiting the judge batch")


class CachedJudge:
    """Caches judge verdicts for one action across every record it processes.

    `lookup` and `call_and_cache` are separate on purpose — the budget check
    (a later task) has to run between a cache miss and the LLM call that follows it.

    Each miss is one side call on *calls* (online when none is given). A batch
    run seeds the cache with the verdicts its judge batches returned, and a call
    its executor holds back reads as awaiting its batch from then on.
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        action_name: str = "unknown",
        *,
        verdicts: dict[str, Any] | None = None,
        calls: SideCallExecutor | None = None,
    ) -> None:
        self._calls = calls or OnlineSideCalls(agent_config, action_name)
        self._cache: dict[CacheKey, tuple[bool, str]] = {
            tuple(json.loads(key)): (bool(verdict[0]), str(verdict[1]))
            for key, verdict in (verdicts or {}).items()
        }

    def lookup(self, expectation: Expectation, value: Any) -> tuple[bool, str] | None:
        return self._cache.get(cache_key(expectation, value))

    def call_and_cache(
        self, expectation: Expectation, value: Any, context: dict[str, Any] | None = None
    ) -> tuple[bool, str]:
        key = cache_key(expectation, value)
        params = expectation.params
        replies = self._calls.run(
            judge_call(
                params["rule"],
                value,
                key=verdict_key(key),
                context=context,
                model=params.get("model"),
                votes=params.get("votes", 1),
            )
        )
        verdict = _AWAITING_BATCH if replies is None else verdict_from_replies(replies)
        self._cache[key] = verdict
        return verdict


class JudgeBudget:
    """Caps how many real judge calls one action's ExpectationService may make this run.

    `max_calls=None` is uncapped — the budget is opt-in, not a default limit.
    """

    @staticmethod
    def at_start(expect_config: dict[str, Any], carried: int | None) -> int | None:
        """What a pass starts with: the balance the last pass *carried*, else the configured cap.

        ``judge_budget`` bounds the whole run. A deferred batch rebuilds its
        service on each pass, so the caller carries what is left.
        """
        return carried if carried is not None else expect_config.get("judge_budget")

    def __init__(self, max_calls: int | None) -> None:
        self._remaining = max_calls
        # Records of one action can run concurrently, so the check and the decrement
        # must be one step.
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
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
