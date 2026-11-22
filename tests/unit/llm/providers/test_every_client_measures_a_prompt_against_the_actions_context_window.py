"""Every vendor's client, online and in batch, measures a prompt against `context_window`.

A model agac does not know gets 128,000 tokens. With `context_window` set, the same
prompt is sent, by the record call and by a judge call, in both run modes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import PromptTooLargeError
from agent_actions.expectations.judge import judge_call
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.side_batch import submit_side_batch
from agent_actions.llm.realtime.builder import create_dynamic_agent
from agent_actions.llm.side_calls import OnlineSideCalls
from tests.unit.llm.providers.test_a_batch_request_asks_what_the_online_request_asks import (
    PROMPT,
    VENDORS,
    _batch_client,
    _config,
    _online_wire,
)

UNKNOWN_MODEL = "a-model-agac-does-not-know"
# 600,000 characters are estimated as 150,000 tokens: above 128,000, below 400,000.
RECORD = {"doc": "x" * 600_000}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "k")


def _sent_online(config: dict[str, Any]) -> bool:
    with _online_wire(config["model_vendor"]) as sent:
        try:
            create_dynamic_agent(config, {"source": RECORD}, PROMPT)
        except PromptTooLargeError:
            return False
    return bool(sent)


def _sent_in_batch(config: dict[str, Any], tmp_path: Any) -> bool:
    prepared = BatchTaskPreparator(storage_backend=MagicMock()).prepare_tasks(
        agent_config=config,
        data=[{"target_id": "r1", "source_guid": "sg-1", "content": RECORD}],
        provider=_batch_client(config["model_vendor"]),
        output_directory=str(tmp_path),
    )
    return len(prepared.tasks) == 1


def _judge_sent(config: dict[str, Any], tmp_path: Any) -> tuple[bool, bool]:
    call = judge_call("Every tag is one word.", "x" * 600_000, key="key")
    with _online_wire(config["model_vendor"]) as sent:
        try:
            OnlineSideCalls(config).run(call)
        except PromptTooLargeError:
            pass
    client = _batch_client(config["model_vendor"])
    with patch.object(client, "submit_batch", return_value=("b1", "submitted")):
        submission = submit_side_batch(
            client,
            call.kind,
            {call.key: call},
            config,
            file_name="f",
            attempt=1,
            output_directory=str(tmp_path),
        )
    return bool(sent), not submission.unsent


@pytest.mark.parametrize("json_mode", [True, False], ids=["json", "text"])
@pytest.mark.parametrize("vendor", VENDORS)
def test_a_record_prompt_is_sent_when_the_context_window_holds_it(vendor, json_mode, tmp_path):
    config = _config(vendor, json_mode=json_mode, schema=json_mode, model_name=UNKNOWN_MODEL)

    assert (_sent_online(config), _sent_in_batch(config, tmp_path)) == (False, False)

    config["context_window"] = 400_000

    assert (_sent_online(config), _sent_in_batch(config, tmp_path)) == (True, True)


@pytest.mark.parametrize("vendor", VENDORS)
def test_a_judge_prompt_is_sent_when_the_context_window_holds_it(vendor, tmp_path):
    config = _config(vendor, json_mode=True, schema=True, model_name=UNKNOWN_MODEL)

    assert _judge_sent(config, tmp_path) == (False, False)

    config["context_window"] = 400_000

    assert _judge_sent(config, tmp_path) == (True, True)
