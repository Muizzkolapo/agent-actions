"""A judge call made directly, and stand-ins for what its side call returns.

A judged rule asks through `CachedJudge`, which makes one side call per value on
the executor it was given: online, `OnlineSideCalls.run`.
"""

import json
from typing import Any

from agent_actions.expectations.judge import CachedJudge
from agent_actions.expectations.types import Expectation
from agent_actions.llm.side_calls import SideReplies

# The online executor's one entry point: every judge call a service makes goes through it.
SIDE_CALL = "agent_actions.llm.side_calls.OnlineSideCalls.run"


def invoke_judge(
    agent_config: dict[str, Any],
    rule: str,
    value: Any,
    *,
    votes: int = 1,
    context: dict[str, Any] | None = None,
    model: str | None = None,
    action_name: str = "unknown",
) -> tuple[bool, str]:
    """Judge *value* by *rule* online, as a judged rule's first sight of a value does."""
    params: dict[str, Any] = {"rule": rule, "votes": votes}
    if model is not None:
        params["model"] = model
    expectation = Expectation(id="judged", type="llm_judge", field="value", params=params)
    return CachedJudge(agent_config, action_name).call_and_cache(expectation, value, context)


def voted(*verdicts: tuple[bool, str]) -> SideReplies:
    """What the executor returns for a call whose votes replied with *verdicts*."""
    return SideReplies(
        tuple(json.dumps({"passed": passed, "reason": reason}) for passed, reason in verdicts)
    )
