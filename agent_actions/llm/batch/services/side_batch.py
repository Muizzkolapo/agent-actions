"""Side batches: a batch run's side calls, sent as batches of their own.

A step about to read a batch's results first asks each registered requester for
the side calls it would make over them (`SideRequester.collect`). The calls of
one kind go out as ``<file>_<kind>_<n>`` and the step defers; once that batch
returns, each call's replies are handed back to its requester (`settle`) and kept
under the call's key, and the step runs again with those calls answered.

A side batch carries one kind and one model, and at most the provider's cap of
requests: a batch is prepared from one config, and its name says what the records
wait on. Calls of another kind or model, or past the cap, are still unanswered when
the step runs again, and go out in the next round.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agent_actions.llm.providers.batch_base import batch_request_cap, raise_unsent
from agent_actions.llm.side_calls import SideCall, SideReplies

if TYPE_CHECKING:
    from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
    from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult

logger = logging.getLogger(__name__)


@dataclass
class SideStep:
    """A step of a batch pass about to read *results*, as a requester sees it.

    ``state`` is the file's recovery state, saved only if a side batch goes out.
    """

    agent_config: dict[str, Any]
    results: list[BatchResult]
    state: RecoveryState
    context_map: dict[str, Any] | None = None

    def settled(self, kind: str) -> dict[str, Any]:
        """What the returned batches of *kind* answered so far, by call key."""
        return self.state.side_results.get(kind, {})


class SideRequester(Protocol):
    """What makes side calls of one kind in a batch run."""

    kind: str

    def collect(self, step: SideStep) -> dict[str, SideCall]:
        """The calls *step* would make that no returned batch has answered, by key."""

    def sent(self, step: SideStep, calls: dict[str, SideCall]) -> None:
        """Told which of its collected calls went out, before the state is saved."""

    def settle(self, key: str, replies: SideReplies) -> Any:
        """The result of the call under *key* from its replies, in a form JSON can store."""


# A kind names its batches (`<file>_<kind>_<n>`) and prefixes its request ids.
_KIND_NAME = re.compile(r"[a-z][a-z0-9]*")
_TAKEN_NAMES = frozenset({"retry", "repair", "side"})

# The modules whose import registers a requester the framework ships.
_BUILT_IN = ("agent_actions.llm.batch.services.judge_ops",)

_requesters: dict[str, SideRequester] = {}


def _load_built_in() -> None:
    for module in _BUILT_IN:
        importlib.import_module(module)


def register_side_requester(requester: SideRequester) -> None:
    """Have *requester* asked at each step of a batch pass, after those already registered."""
    kind = requester.kind
    if not _KIND_NAME.fullmatch(kind) or kind in _TAKEN_NAMES:
        raise ValueError(
            f"Side-call kind {kind!r} cannot name a batch: use lowercase letters and digits, "
            f"starting with a letter, and none of {sorted(_TAKEN_NAMES)}"
        )
    _load_built_in()
    _requesters[kind] = requester


def unregister_side_requester(kind: str) -> None:
    _requesters.pop(kind, None)


def side_requesters() -> list[SideRequester]:
    """Every registered requester, the built-in ones first, in registration order."""
    _load_built_in()
    return list(_requesters.values())


def side_requester(kind: str) -> SideRequester:
    for requester in side_requesters():
        if requester.kind == kind:
            return requester
    raise ValueError(
        f"A {kind} batch is out, but nothing is registered to read side calls of kind {kind!r}"
    )


@dataclass(frozen=True)
class SideSubmission:
    """A side batch in flight: each request id to the key of the call it is a copy of."""

    batch_id: str
    requests: dict[str, str]
    sent: dict[str, SideCall]


def _request_id(kind: str, key: str, copy: int) -> str:
    # Provider-safe whatever the key holds: Anthropic takes at most 64 of [A-Za-z0-9_-].
    return f"{kind[0]}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}_{copy}"


def submit_side_batch(
    provider: BaseBatchClient,
    kind: str,
    calls: dict[str, SideCall],
    agent_config: dict[str, Any],
    *,
    file_name: str,
    attempt: int,
    output_directory: str,
) -> SideSubmission:
    """Send one request per copy of each call, as ``<file>_<kind>_<attempt>``.

    A batch takes one model and at most the provider's cap of requests, so only the
    calls of the first model met go out, up to that cap.
    """
    first = next(iter(calls.values()))
    cap = batch_request_cap(provider)
    sent: dict[str, SideCall] = {}
    held = 0
    for key, call in calls.items():
        if call.model != first.model:
            continue
        if sent and held + call.copies > cap:
            break
        sent[key] = call
        held += call.copies

    rows: list[dict[str, Any]] = []
    requests: dict[str, str] = {}
    for key, call in sent.items():
        for copy in range(call.copies):
            request_id = _request_id(kind, key, copy)
            requests[request_id] = key
            # As the online executor sends it: the prompt, with no record content beside it.
            rows.append({"target_id": request_id, "prompt": call.prompt, "content": ""})

    config = first.request_config(agent_config)
    config.pop("compiled_schema", None)
    batch_name = f"{file_name}_{kind}_{attempt}"
    tasks = provider.prepare_tasks(rows, config)
    raise_unsent(rows)
    batch_id, _status = provider.submit_batch(
        tasks=tasks, batch_name=batch_name, output_directory=output_directory
    )
    logger.info(
        "%s batch %s submitted as %s: %d request(s) for %d call(s)",
        kind.capitalize(),
        batch_id,
        batch_name,
        len(tasks),
        len(sent),
    )
    return SideSubmission(batch_id=batch_id, requests=requests, sent=sent)


def read_side_batch(
    results: list[BatchResult], requests: dict[str, str], kind: str
) -> dict[str, SideReplies]:
    """Each call's replies from a returned side batch, by key.

    A request that errored, or that the batch returned no line for, fails its
    whole call, as an online call fails when one copy raises.
    """
    by_id = {str(result.custom_id): result for result in results}
    replies: dict[str, list[Any]] = {}
    errors: dict[str, str] = {}
    for request_id, key in requests.items():
        result = by_id.get(request_id)
        if result is None:
            errors.setdefault(key, f"the {kind} batch returned no reply for this request")
            continue
        if not result.success:
            errors.setdefault(key, result.error or f"the {kind} request failed")
            continue
        replies.setdefault(key, []).append(
            result.text if result.text is not None else result.content
        )

    return {
        key: SideReplies(error=errors[key]) if key in errors else SideReplies(tuple(replies[key]))
        for key in dict.fromkeys(requests.values())
    }
