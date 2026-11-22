"""In run_mode: batch, an action's llm_judge calls go out as a batch, not online (1814).

Driven through `check_and_submit_repair`, the step that runs once a main batch has come
back, as in test_repair_deferral. The model is never called online here: any online
judge call is recorded and counted as a failure of the test.
"""

from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

from .recording_provider import RecordingProvider
from .test_repair_deferral import (
    FILE,
    _agent_config,
    _Backend,
    _context,
    _context_map,
    _identity,
    _prepared,
    _state,
)

RECORDS = 10
VOTES = 3
JUDGED = [
    {
        "id": "on_topic",
        "type": "llm_judge",
        "field": "options",
        "params": {"rule": "Every option is on topic.", "votes": VOTES},
    }
]


class NamingProvider(RecordingProvider):
    """Also keeps the name of each batch it was asked to submit."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[tuple[str, int]] = []

    def submit_batch(self, tasks, batch_name, output_directory):
        self.batches.append((batch_name, len(tasks)))
        return super().submit_batch(tasks, batch_name, output_directory)


def _judged_config(repair: str) -> dict[str, Any]:
    config = _agent_config(repair=repair)
    config["model_vendor"] = "openai"
    config["expect"]["expectations"] = JUDGED
    return config


def _answers() -> list[BatchResult]:
    return [
        BatchResult(custom_id=f"r{i}", content={"options": [f"a{i}", f"b{i}"]}, success=True)
        for i in range(RECORDS)
    ]


def _run(repair: str):
    provider = NamingProvider()
    backend = _Backend()
    online: list[Any] = []

    def no_online_call(**kwargs):
        online.append(kwargs)
        return [{"passed": True, "reason": "online"}]

    results = _answers()
    with (
        patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare",
            return_value=_prepared(),
        ),
        patch(
            "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client",
            side_effect=no_online_call,
        ),
    ):
        should_continue = pr.check_and_submit_repair(
            _context(provider, backend, _judged_config(repair)),
            _identity(),
            batch_results=results,
            context_map=_context_map(*[r.custom_id for r in results]),
        )
    return should_continue, provider, backend, online


@pytest.mark.parametrize("repair", ["auto", "none"])
def test_the_judge_calls_go_out_as_one_batch_and_none_online(repair):
    should_continue, provider, backend, online = _run(repair)

    assert online == [], f"{len(online)} judge call(s) were sent online"
    assert provider.batches == [(f"{FILE}_judge_1", RECORDS * VOTES)]
    # The workflow pauses on the judge batch, as it does on a repair batch.
    assert should_continue is False
    assert _state(backend) is not None


def test_each_judge_request_is_one_vote_on_one_record():
    _should, provider, _backend, _online = _run("auto")

    ids = sorted(task["custom_id"] for task in provider.submitted)
    assert len(set(ids)) == RECORDS * VOTES, "each (record, rule, vote) needs its own id"
    first = provider.submitted[0]["body"]["messages"]
    text = " ".join(m["content"] for m in first)
    assert "Every option is on topic." in text
    assert '{"passed": true' in text
