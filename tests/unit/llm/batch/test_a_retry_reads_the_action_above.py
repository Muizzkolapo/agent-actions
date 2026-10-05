"""A retry rebuilds its record's prompt, which for an action below another reads that one.

The retry service is built with the workflow's action positions and configs for this.
Preparation refuses an action with dependencies when it is handed no positions, and a
guard on an upstream's `output_field` reads nothing without the configs. A retry
prepared without them is not sent, and its record ends as one the batch lost.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_actions.llm.batch.services.retry import BatchRetryService

from .recording_provider import RecordingProvider

UPSTREAM = "summarize"
ACTION = "publish"
LOST = "t-1"
ANSWER_ABOVE = "what the action above said"

_CONFIG: dict[str, Any] = {
    "name": ACTION,
    "action_name": ACTION,
    "agent_type": ACTION,
    "kind": "llm",
    "json_mode": False,
    "model_name": "test-model",
    "run_mode": "batch",
    "prompt": "Restate: {{ summarize.summary }}",
    "dependencies": [UPSTREAM],
    "context_scope": {"observe": [f"{UPSTREAM}.summary"]},
    "retry": {"enabled": True, "max_attempts": 1},
}


def _service(upstream: dict[str, Any] | None = None) -> BatchRetryService:
    return BatchRetryService(
        action_indices={UPSTREAM: 0, ACTION: 1},
        dependency_configs={
            UPSTREAM: {"name": UPSTREAM, "idx": 0, **(upstream or {})},
            ACTION: {**_CONFIG, "idx": 1},
        },
    )


def _context_map(**answer_above: Any) -> dict[str, Any]:
    return {
        LOST: {
            "target_id": LOST,
            "source_guid": "sg-1",
            "content": {UPSTREAM: {"summary": ANSWER_ABOVE, **answer_above}},
        }
    }


def _sent_prompts(provider: RecordingProvider) -> list[str]:
    return [task["body"]["messages"][0]["content"] for task in provider.submitted]


def test_a_retry_sent_without_waiting_carries_the_answer_above(tmp_path):
    provider = RecordingProvider()

    submission = _service().submit_retry_batch(
        provider=provider,
        missing_ids={LOST},
        context_map=_context_map(),
        output_directory=str(tmp_path),
        file_name="pages.json",
        agent_config=_CONFIG,
    )

    assert submission == ("batch-1", 1)
    assert _sent_prompts(provider) == [f"Restate: {ANSWER_ABOVE}"]


def test_a_retry_waited_on_carries_the_answer_above(tmp_path):
    """The blocking loop prepares its retries through a function of its own."""
    provider = RecordingProvider()

    _service().retrieve_results_with_retry(
        provider,
        "batch-0",
        str(tmp_path),
        context_map=_context_map(),
        file_name="pages.json",
        agent_config=_CONFIG,
    )

    assert _sent_prompts(provider) == [f"Restate: {ANSWER_ABOVE}"]


def _send_without_waiting(
    service: BatchRetryService, config: dict[str, Any], context_map: dict[str, Any], out: Path
) -> RecordingProvider:
    provider = RecordingProvider()
    service.submit_retry_batch(
        provider=provider,
        missing_ids={LOST},
        context_map=context_map,
        output_directory=str(out),
        file_name="pages.json",
        agent_config=config,
    )
    return provider


def _send_waited_on(
    service: BatchRetryService, config: dict[str, Any], context_map: dict[str, Any], out: Path
) -> RecordingProvider:
    provider = RecordingProvider()
    service.retrieve_results_with_retry(
        provider,
        "batch-0",
        str(out),
        context_map=context_map,
        file_name="pages.json",
        agent_config=config,
    )
    return provider


Send = Callable[[BatchRetryService, dict[str, Any], dict[str, Any], Path], RecordingProvider]
_SENDERS = pytest.mark.parametrize(
    "send", [_send_without_waiting, _send_waited_on], ids=["sent without waiting", "waited on"]
)


@_SENDERS
def test_a_retry_passes_a_guard_on_the_answer_above(send: Send, tmp_path):
    """The guard reads the action above's `output_field` by its bare name, which only
    that action's config promotes."""
    config = {
        **_CONFIG,
        "context_scope": {"observe": [f"{UPSTREAM}.summary", f"{UPSTREAM}.verdict"]},
        "guard": {"clause": 'verdict == "go"', "behavior": "skip"},
    }

    provider = send(
        _service(upstream={"output_field": "verdict"}),
        config,
        _context_map(verdict="go"),
        tmp_path,
    )

    assert _sent_prompts(provider) == [f"Restate: {ANSWER_ABOVE}"]
