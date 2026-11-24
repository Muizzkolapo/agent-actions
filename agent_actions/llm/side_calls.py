"""Side calls: the model requests an action makes besides its main one.

A requester (an ``llm_judge`` rule is one) turns what it needs into a `SideCall`
and the replies back into its own result. An executor runs the call the way the
action's run mode says: `OnlineSideCalls` now, `HeldSideCalls` held back, for a
batch run to send with the step's other held calls as a batch of their own. The
requester is handed an executor and does not know which.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from agent_actions.llm.providers.usage_tracker import counted_as
from agent_actions.output.response.response_builder import ResponseBuilder


@dataclass(frozen=True)
class SideCall:
    """One request a requester of *kind* makes, and how many independent copies of it to run.

    ``key`` names what the call decides and is stable across passes: a batch run
    hands the replies back under it. ``model`` None is the action's own model.
    """

    kind: str
    key: str
    prompt: str
    model: str | None = None
    copies: int = 1

    def request_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """The action's config as each copy is sent under it, online or in a batch."""
        from agent_actions.prompt.cache_scope import REQUEST_VARIES_PER_RECORD_KEY

        # json_mode False: the requester reads the model's own text, not a best-effort
        # parse. The prompt is this call's alone, so it gets no prompt-cache mark.
        config = {**agent_config, "json_mode": False, REQUEST_VARIES_PER_RECORD_KEY: True}
        if self.model is not None:
            config["model_name"] = self.model
        return config


@dataclass(frozen=True)
class SideReplies:
    """What the copies of one side call answered, in order.

    A reply is the text the model wrote, or what the provider parsed of it; None
    is a copy that answered nothing. ``error`` is set, and ``replies`` empty, when
    a batch could not answer the call; online, the failure is raised instead.
    """

    replies: tuple[Any, ...] = ()
    error: str | None = None


class SideCallExecutor(Protocol):
    """Runs a side call the way the action's run mode says."""

    def run(self, call: SideCall) -> SideReplies | None:
        """The call's replies, or None when it is held for a batch that answers it on a later
        pass."""


class OnlineSideCalls:
    """Runs each side call now, its copies in parallel."""

    def __init__(self, agent_config: dict[str, Any], action_name: str = "unknown") -> None:
        self._agent_config = agent_config
        self._action_name = action_name

    def run(self, call: SideCall) -> SideReplies:
        """Raises whatever `ClientInvocationService.invoke_client` raises for any copy."""
        # The copies' usage is counted under the call's kind, not as the action's main call.
        with counted_as(call.kind):
            if call.copies <= 1:
                return SideReplies((self._one_copy(call),))
            # Each copy runs in a copy of this context, so its model call is logged
            # against the action that asked for it.
            with ThreadPoolExecutor(max_workers=call.copies) as pool:
                futures = [
                    pool.submit(contextvars.copy_context().run, self._one_copy, call)
                    for _ in range(call.copies)
                ]
                return SideReplies(tuple(future.result() for future in futures))

    def _one_copy(self, call: SideCall) -> Any:
        from agent_actions.llm.realtime.services.invocation import ClientInvocationService

        model_vendor = self._agent_config.get("model_vendor")
        if not model_vendor:
            raise ValueError(
                f"agent_config missing required 'model_vendor' for {call.kind} LLM call"
            )
        config = call.request_config(self._agent_config)
        result = ClientInvocationService.invoke_client(
            model_vendor=model_vendor,
            agent_config=config,
            prompt_config=call.prompt,
            context_data="",
            schema=None,
            granularity="record",
            action_name=f"{self._action_name}_{call.kind}",
        )
        return ResponseBuilder.unwrap(result, config) if result else None


class HeldSideCalls:
    """Holds each side call back, by key, for a batch run to send."""

    def __init__(self) -> None:
        self.pending: dict[str, SideCall] = {}

    def run(self, call: SideCall) -> None:
        self.pending[call.key] = call
        return None
