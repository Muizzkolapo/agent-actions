"""An action whose batch reports a status agac does not know asks the provider again.

The registry knows only `BatchStatus`. An entry holding anything else was neither in flight
nor finished, so the registry rolled the action up to `error` and the run failed it without
asking the provider about any batch; the run after sent every file again. Statuses that got
there: Gemini's raw state name at submit, OpenAI `expired` and `cancelling`, Groq
`cancelling`, Anthropic `canceling`, and a registry an earlier version wrote holding them.

Driven through the harness of the collect-pass tests beside this one: the real lifecycle
manager, job manager, registry and collect pass over a SQLite store. Where a vendor is
named, its batch client runs unchanged over a stand-in for its SDK client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace as NS
from typing import Any

import pytest
from google.genai.types import JobState

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.storage.backend import DISPOSITION_FAILED
from tests.unit.workflow.managers.test_a_file_the_collect_pass_could_not_read import (
    ACTION,
    PAGES,
    _Action,
)


def _statuses(action: _Action) -> dict[str, str]:
    jobs = BatchRegistryManager(action.backend, ACTION).get_all_jobs()
    return {name: entry.status for name, entry in jobs.items()}


def _asked(action: _Action) -> list[str]:
    """Record each batch the provider is asked about."""
    asked: list[str] = []
    answer = action.provider.check_status

    def check_status(batch_id: str) -> str:
        asked.append(batch_id)
        return answer(batch_id)

    action.provider.check_status = check_status
    return asked


@pytest.mark.parametrize(
    "recorded", ["JOB_STATE_PENDING", "expired", "cancelling", "canceling", "on_hold"]
)
def test_an_entry_an_earlier_version_recorded_unmapped_is_asked_about(tmp_path, recorded):
    """Failed unasked, the action was sent whole again by the run after, and an entry
    recorded at submit this way failed it every time."""
    action = _Action(tmp_path, statuses={"page2.json": recorded})
    action.provider.statuses["batch-page2.json"] = BatchStatus.COMPLETED
    asked = _asked(action)

    assert action.check() == (action.out, "completed")
    assert "batch-page2.json" in asked
    assert action.finalized == list(PAGES)


def test_an_entry_recorded_unmapped_beside_one_still_out_waits(tmp_path):
    action = _Action(
        tmp_path, statuses={"page1.json": BatchStatus.IN_PROGRESS, "page2.json": "cancelling"}
    )
    action.provider.statuses["batch-page2.json"] = BatchStatus.IN_PROGRESS

    assert action.check() == (None, "in_progress")
    assert action.finalized == []


@dataclass
class _Vendor:
    """A batch client over a stand-in for its SDK client, which reports ``reports``."""

    name: str
    client: Any
    finished: str
    reports: dict[str, str]


def _openai_compatible(name: str, client_type, finished: str) -> _Vendor:
    vendor = _Vendor(name, client_type(api_key="test"), finished, {})
    vendor.client.client = NS(
        batches=NS(retrieve=lambda batch_id: NS(id=batch_id, status=vendor.reports[batch_id]))
    )
    return vendor


def _openai() -> _Vendor:
    return _openai_compatible("openai", OpenAIBatchClient, "completed")


def _groq() -> _Vendor:
    return _openai_compatible("groq", GroqBatchClient, "completed")


def _anthropic() -> _Vendor:
    vendor = _Vendor("anthropic", AnthropicBatchClient(api_key="test"), "ended", {})
    vendor.client.client = NS(
        messages=NS(
            batches=NS(
                retrieve=lambda batch_id: NS(
                    id=batch_id, processing_status=vendor.reports[batch_id]
                )
            )
        )
    )
    return vendor


def _gemini() -> _Vendor:
    vendor = _Vendor("gemini", GeminiBatchClient(api_key="test"), "JOB_STATE_SUCCEEDED", {})

    def get(name: str) -> NS:
        reported = vendor.reports[name]
        state = JobState[reported] if reported in JobState.__members__ else NS(name=reported)
        return NS(name=name, state=state)

    vendor.client.client = NS(batches=NS(get=get))
    return vendor


def _page2_out_with(tmp_path, vendor: _Vendor, reported: str) -> _Action:
    """page2.json's batch was out at the last poll and now reports *reported*; the other
    files' batches have finished."""
    action = _Action(tmp_path, statuses={"page2.json": BatchStatus.IN_PROGRESS})
    for name in PAGES:
        action.send(name, f"{name}-a", f"{name}-b")
    vendor.reports.update({f"batch-{name}": vendor.finished for name in PAGES})
    vendor.reports["batch-page2.json"] = reported
    action.provider.check_status = vendor.client.check_status
    return action


ENDING = [
    pytest.param(_openai, "cancelling", "cancelled", id="openai"),
    pytest.param(_groq, "cancelling", "cancelled", id="groq"),
    pytest.param(_gemini, "JOB_STATE_CANCELLING", "JOB_STATE_CANCELLED", id="gemini"),
]


@pytest.mark.parametrize(("vendor", "ending", "_ended"), ENDING)
def test_a_batch_being_cancelled_is_waited_for(tmp_path, vendor, ending, _ended):
    action = _page2_out_with(tmp_path, vendor(), ending)

    assert action.check() == (None, "in_progress")
    assert _statuses(action)["page2.json"] in BatchStatus.in_flight_states()
    assert action.dispositions() == {}


@pytest.mark.parametrize(("vendor", "ending", "ended"), ENDING)
def test_once_cancelled_its_records_are_failed_and_the_action_completes(
    tmp_path, vendor, ending, ended
):
    """The run after asks the provider again, which by then reports it cancelled."""
    vendor = vendor()
    action = _page2_out_with(tmp_path, vendor, ending)
    action.check()
    vendor.reports["batch-page2.json"] = ended

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page3.json"]
    assert action.dispositions() == {
        "page2.json-a": DISPOSITION_FAILED,
        "page2.json-b": DISPOSITION_FAILED,
    }


def test_an_anthropic_batch_being_canceled_is_waited_for_then_read(tmp_path):
    """Anthropic ends a canceled batch like any other, with a result for every request."""
    vendor = _anthropic()
    action = _page2_out_with(tmp_path, vendor, "canceling")

    assert action.check() == (None, "in_progress")
    vendor.reports["batch-page2.json"] = "ended"
    assert action.check() == (action.out, "completed")
    assert action.finalized == list(PAGES)


@pytest.mark.parametrize(
    ("vendor", "expired"),
    [
        pytest.param(_openai, "expired", id="openai"),
        pytest.param(_groq, "expired", id="groq"),
        pytest.param(_gemini, "JOB_STATE_EXPIRED", id="gemini"),
    ],
)
def test_a_batch_that_expired_has_its_records_failed_beside_those_collected(
    tmp_path, vendor, expired, caplog
):
    """Nothing will come back for it. The batches beside it are read in the same run."""
    action = _page2_out_with(tmp_path, vendor(), expired)

    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.batch.services.processing"):
        assert action.check() == (action.out, "completed")

    assert action.finalized == ["page1.json", "page3.json"]
    assert action.dispositions() == {
        "page2.json-a": DISPOSITION_FAILED,
        "page2.json-b": DISPOSITION_FAILED,
    }
    assert "Could not read page2.json (batch batch-page2.json)" in caplog.text


@pytest.mark.parametrize("vendor", [_openai, _groq, _anthropic, _gemini])
def test_a_status_no_mapping_knows_is_waited_for_and_asked_about_again(tmp_path, vendor):
    """A status an SDK adds later: the run waits, and the run after asks again."""
    vendor = vendor()
    action = _page2_out_with(tmp_path, vendor, "JOB_STATE_ON_HOLD")

    assert action.check() == (None, "in_progress")
    assert action.dispositions() == {}
    vendor.reports["batch-page2.json"] = vendor.finished
    assert action.check() == (action.out, "completed")
    assert action.finalized == list(PAGES)
