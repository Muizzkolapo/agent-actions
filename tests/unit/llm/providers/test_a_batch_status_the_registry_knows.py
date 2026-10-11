"""Every status a batch client answers is one the batch registry knows.

The registry knows only `BatchStatus`. A status outside it was stored as the client gave
it, and an entry holding one is neither in flight nor finished: the next run failed the
action without asking the provider about any batch. Gemini's submit answered the SDK's
raw state name for every batch; OpenAI `expired` and `cancelling`, Groq `cancelling`,
Anthropic `canceling` and most Gemini states passed through a poll unmapped.

Each client runs unchanged; only its SDK client is stood in for, answering every value of
the SDK's own status type.
"""

from __future__ import annotations

import logging
import typing
from types import SimpleNamespace as NS

import pytest
from anthropic.types.messages import MessageBatch
from google.genai.types import JobState
from groq.types import BatchCreateResponse, BatchRetrieveResponse
from openai.types import Batch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

KNOWN = {status.value for status in BatchStatus}
IN_FLIGHT = {status.value for status in BatchStatus.in_flight_states()}

OPENAI = typing.get_args(Batch.model_fields["status"].annotation)
GROQ = typing.get_args(BatchRetrieveResponse.model_fields["status"].annotation)
GROQ_AT_SUBMIT = typing.get_args(BatchCreateResponse.model_fields["status"].annotation)
ANTHROPIC = typing.get_args(MessageBatch.model_fields["processing_status"].annotation)
GEMINI = [state.name for state in JobState]


def _openai_compatible(client_type, status: str):
    client = client_type(api_key="test")
    client.client = NS(
        files=NS(create=lambda file, purpose: NS(id="file-1")),
        batches=NS(
            create=lambda **kwargs: NS(id="batch_1", status=status),
            retrieve=lambda batch_id: NS(id=batch_id, status=status),
        ),
    )
    return client


def _openai(status: str) -> OpenAIBatchClient:
    return _openai_compatible(OpenAIBatchClient, status)


def _groq(status: str) -> GroqBatchClient:
    return _openai_compatible(GroqBatchClient, status)


def _anthropic(status: str) -> AnthropicBatchClient:
    client = AnthropicBatchClient(api_key="test")
    client.client = NS(
        messages=NS(
            batches=NS(
                create=lambda requests: NS(id="msgbatch_1", processing_status=status),
                retrieve=lambda batch_id: NS(id=batch_id, processing_status=status),
            )
        )
    )
    return client


def _gemini(status: str) -> GeminiBatchClient:
    state = JobState[status] if status in JobState.__members__ else NS(name=status)
    client = GeminiBatchClient(api_key="test")
    client.client = NS(
        files=NS(upload=lambda file, config: NS(name="files/in-1")),
        batches=NS(
            create=lambda model, src, config: NS(name="batches/1", state=state),
            get=lambda name: NS(name=name, state=state),
        ),
    )
    return client


EVERY_STATUS = (
    [pytest.param(_openai, s, id=f"openai-{s}") for s in OPENAI]
    + [pytest.param(_groq, s, id=f"groq-{s}") for s in GROQ]
    + [pytest.param(_anthropic, s, id=f"anthropic-{s}") for s in ANTHROPIC]
    + [pytest.param(_gemini, s, id=f"gemini-{s}") for s in GEMINI]
)

EVERY_STATUS_AT_SUBMIT = (
    [pytest.param(_openai, s, id=f"openai-{s}") for s in OPENAI]
    + [pytest.param(_groq, s, id=f"groq-{s}") for s in GROQ_AT_SUBMIT]
    + [pytest.param(_anthropic, s, id=f"anthropic-{s}") for s in ANTHROPIC]
    + [pytest.param(_gemini, s, id=f"gemini-{s}") for s in GEMINI]
)


def _submit(client, tmp_path) -> str:
    tasks = [{"custom_id": "r1", "key": "r1", "request": {}, "params": {}}]
    _batch_id, status = client.submit_batch(tasks, "page.json", str(tmp_path))
    return status


@pytest.mark.parametrize(("client", "status"), EVERY_STATUS)
def test_every_status_a_poll_answers_is_one_the_registry_knows(client, status):
    assert client(status).check_status("batch_1") in KNOWN


@pytest.mark.parametrize(("client", "status"), EVERY_STATUS_AT_SUBMIT)
def test_every_status_a_submit_answers_is_one_the_registry_knows(client, status, tmp_path):
    assert _submit(client(status), tmp_path) in KNOWN


def test_a_gemini_batch_just_submitted_is_in_flight(tmp_path):
    """Gemini answers JOB_STATE_PENDING for every batch it takes."""
    assert _submit(_gemini("JOB_STATE_PENDING"), tmp_path) in IN_FLIGHT


@pytest.mark.parametrize(
    ("client", "status"),
    [
        pytest.param(_openai, "cancelling", id="openai"),
        pytest.param(_groq, "cancelling", id="groq"),
        pytest.param(_anthropic, "canceling", id="anthropic"),
        pytest.param(_gemini, "JOB_STATE_CANCELLING", id="gemini"),
        pytest.param(_gemini, "JOB_STATE_QUEUED", id="gemini-queued"),
        pytest.param(_gemini, "JOB_STATE_PAUSED", id="gemini-paused"),
        pytest.param(_gemini, "JOB_STATE_UPDATING", id="gemini-updating"),
    ],
)
def test_a_batch_the_provider_has_not_finished_with_is_in_flight(client, status):
    """It ends at the provider later, and only a poll then can say how."""
    assert client(status).check_status("batch_1") in IN_FLIGHT


@pytest.mark.parametrize(
    ("client", "status"),
    [
        pytest.param(_openai, "expired", id="openai"),
        pytest.param(_groq, "expired", id="groq"),
        pytest.param(_gemini, "JOB_STATE_EXPIRED", id="gemini"),
    ],
)
def test_a_batch_that_ran_out_of_time_failed(client, status):
    """Its records are then marked failed for `agac retry`, as for any batch that failed."""
    assert client(status).check_status("batch_1") == BatchStatus.FAILED


def test_a_gemini_batch_that_partly_succeeded_is_read(tmp_path):
    """Its results are written for the requests that succeeded; failed outright, the
    requests the provider answered would be paid for again."""
    client = _gemini("JOB_STATE_PARTIALLY_SUCCEEDED")
    client.client.batches.get = lambda name: NS(
        name=name,
        state=JobState.JOB_STATE_PARTIALLY_SUCCEEDED,
        dest=NS(file_name="files/out-1"),
    )
    client.client.files.download = lambda file: (
        b'{"key": "r1", "response": {"candidates": [{"content": {"parts": [{"text": "\\"hi\\""}]}}]}}\n'
    )

    assert client.check_status("batches/1") == BatchStatus.COMPLETED
    results = client.retrieve_results("batches/1", str(tmp_path))
    assert [(result.custom_id, result.success) for result in results] == [("r1", True)]


UNMAPPED = [
    pytest.param(_openai, "on_hold", id="openai"),
    pytest.param(_groq, "on_hold", id="groq"),
    pytest.param(_anthropic, "on_hold", id="anthropic"),
    pytest.param(_gemini, "JOB_STATE_ON_HOLD", id="gemini"),
]


@pytest.mark.parametrize(("client", "status"), UNMAPPED)
def test_a_status_no_mapping_knows_is_asked_about_again(client, status, caplog):
    """An SDK can add a status. Taken for an error, it failed the action unasked; taken
    for an end, it would fail records the provider may still answer."""
    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.providers.batch_base"):
        answered = client(status).check_status("batch_1")

    assert answered in IN_FLIGHT
    assert "batch_1" in caplog.text and status in caplog.text


@pytest.mark.parametrize(("client", "status"), UNMAPPED)
def test_a_status_no_mapping_knows_at_submit_is_in_flight(client, status, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.providers.batch_base"):
        answered = _submit(client(status), tmp_path)

    assert answered in IN_FLIGHT
    assert status in caplog.text


@pytest.fixture
def agac_project(tmp_path):
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=tmp_path))
    yield tmp_path
    path_utils._global_path_manager = previous


def test_a_batch_the_agac_provider_has_no_record_of_failed(agac_project):
    """Nothing will ever come back for it. Asked about again, it would hold the action
    for good; failed, its records go to `agac retry`."""
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

    assert AgacBatchClient().check_status("mock_batch_never_submitted") == BatchStatus.FAILED
