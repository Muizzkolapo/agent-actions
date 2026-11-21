"""A record whose prompt is too large for the model fails alone in batch, as online fails its call."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import PromptTooLargeError
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.side_batch import submit_side_batch
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.llm.realtime.builder import create_dynamic_agent
from agent_actions.llm.side_calls import SideCall
from agent_actions.processing.invocation.batch import BatchStrategy
from agent_actions.processing.prepared_task import PreparedTask
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_FAILED

PROMPT = "Summarise the document."
# gpt-4 reads 8,192 tokens; 40,000 characters are estimated as 10,000.
LARGE = {"doc": "x" * 40_000}
SMALL = {"doc": "short"}
CONFIG: dict[str, Any] = {
    "agent_type": "summarize",
    "action_name": "summarize",
    "name": "summarize",
    "model_vendor": "openai",
    "model_name": "gpt-4",
    "api_key": "TEST_PROVIDER_KEY",
    "json_mode": True,
    "granularity": "record",
    "prompt": PROMPT,
    "schema": {"summary": "string"},
    "context_scope": {"observe": ["source.doc"]},
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "k")


def _prepare(tmp_path: Any, backend: Any) -> Any:
    return BatchTaskPreparator(storage_backend=backend).prepare_tasks(
        agent_config=CONFIG,
        data=[
            {"target_id": "large", "source_guid": "sg-large", "content": LARGE},
            {"target_id": "small", "source_guid": "sg-small", "content": SMALL},
        ],
        provider=OpenAIBatchClient(api_key="k"),
        output_directory=str(tmp_path),
    )


def _online_error() -> str:
    with pytest.raises(PromptTooLargeError) as raised:
        create_dynamic_agent(CONFIG, {"source": LARGE}, PROMPT)
    return str(raised.value)


def test_the_other_records_of_the_batch_are_still_sent(tmp_path):
    prepared = _prepare(tmp_path, MagicMock())

    assert [task["custom_id"] for task in prepared.tasks] == ["small"]
    assert BatchContextMetadata.is_included(prepared.context_map["small"])
    assert (prepared.stats.included_items, prepared.stats.error_items) == (1, 1)


def test_the_record_fails_with_the_error_online_raises_for_it(tmp_path):
    backend = MagicMock()
    prepared = _prepare(tmp_path, backend)

    entry = prepared.context_map["large"]
    error = _online_error()
    assert "exceeds model context window (8192 tokens)" in error
    assert BatchContextMetadata.get_filter_status(entry) == FilterStatus.FAILED
    assert BatchContextMetadata.get_prep_error(entry) == error[:500]
    assert entry["_state"] == RecordState.FAILED.value
    backend.set_disposition.assert_called_once_with(
        "summarize", "sg-large", DISPOSITION_FAILED, reason=error[:500]
    )


@pytest.mark.parametrize("kind", ["judge", "probe"])
def test_a_side_request_too_large_for_the_model_fails_its_call_and_the_rest_go_out(kind, tmp_path):
    client = OpenAIBatchClient(api_key="k")
    client.submit_batch = MagicMock(return_value=("b1", "submitted"))
    # A judge call is a text call, measured against the default window of 128,000 tokens.
    large = SideCall(kind=kind, key="large", prompt="x" * 600_000)
    small = SideCall(kind=kind, key="small", prompt="Is it on topic?")

    submission = submit_side_batch(
        client,
        kind,
        {"large": large, "small": small},
        CONFIG,
        file_name="f",
        attempt=1,
        output_directory=str(tmp_path),
    )

    (error,) = submission.unsent.values()
    assert list(submission.unsent) == ["large"]
    assert error.startswith("Estimated prompt size")
    assert "exceeds model context window (128000 tokens)" in error
    assert set(submission.requests.values()) == {"small"}
    assert set(submission.sent) == {"large", "small"}
    (sent,) = client.submit_batch.call_args.kwargs["tasks"]
    assert "Is it on topic?" in str(sent["body"]["messages"])


def test_a_side_batch_where_no_request_fits_is_not_submitted(tmp_path):
    client = OpenAIBatchClient(api_key="k")
    client.submit_batch = MagicMock(return_value=("b1", "submitted"))
    call = SideCall(kind="judge", key="large", prompt="x" * 600_000)

    submission = submit_side_batch(
        client,
        "judge",
        {"large": call},
        CONFIG,
        file_name="f",
        attempt=1,
        output_directory=str(tmp_path),
    )

    assert submission.batch_id is None
    assert submission.requests == {}
    assert list(submission.unsent) == ["large"]
    client.submit_batch.assert_not_called()


def test_a_queued_task_too_large_for_the_model_is_raised_not_dropped():
    client = OpenAIBatchClient(api_key="k")
    client.submit_batch = MagicMock(return_value=("b1", "submitted"))
    strategy = BatchStrategy(client)
    config = {**CONFIG, "compiled_schema": {"name": "s", "schema": {"type": "object"}}}
    task = PreparedTask(
        target_id="large", source_guid="sg-large", formatted_prompt=PROMPT, llm_context=LARGE
    )
    strategy.invoke(task, SimpleNamespace(agent_config=config))

    with pytest.raises(PromptTooLargeError, match="exceeds model context window"):
        strategy.flush()
    client.submit_batch.assert_not_called()
