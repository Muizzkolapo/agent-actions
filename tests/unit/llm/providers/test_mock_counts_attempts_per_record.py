"""The mock counts the attempts of each record on its own.

The attempt changes what the mock writes, and a repair round is the next attempt of the
same record. Two records of one action each start at the first attempt, and the first
repair of each is its second attempt, whatever the order of the calls. Each run counts
again from the first attempt.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_actions.config.types import RunMode
from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.logging.core.manager import get_manager
from agent_actions.processing.invocation.online import OnlineStrategy

SCHEMA = {
    "type": "object",
    "properties": {"ideas": {"type": "array", "items": {"type": "string"}}},
    "required": ["ideas"],
}

# No mock array is this long, so every answer fails and is repaired once.
NEVER_MET = Suite(
    name="s",
    expectations=[{"id": "many", "type": "item_count", "field": "ideas", "params": {"min": 99}}],
)


@pytest.fixture(autouse=True)
def _fresh_mock():
    AgacClient.reset()
    yield
    AgacClient.reset()


@pytest.fixture
def attempts(monkeypatch):
    """Each attempt the mock answers with, in call order."""
    seen: list[int] = []
    original = AgacClient._get_attempt_count.__func__

    def spy(cls, *args):
        attempt = original(cls, *args)
        seen.append(attempt)
        return attempt

    monkeypatch.setattr(AgacClient, "_get_attempt_count", classmethod(spy))
    return seen


def _context():
    return SimpleNamespace(
        agent_name="brainstorm",
        agent_config={
            "name": "brainstorm",
            "agent_type": "brainstorm",
            "kind": "llm",
            "model_name": "mock",
            "model_vendor": "agac-provider",
            "json_mode": True,
            "json_output_schema": SCHEMA,
        },
        storage_backend=None,
        mode=RunMode.ONLINE,
        workflow_metadata={},
    )


def _task(record_id: str):
    return SimpleNamespace(
        should_execute=True,
        is_passthrough=False,
        original_content={"topic": "tea"},
        passthrough_fields={},
        formatted_prompt="List ideas about tea.",
        llm_context={"topic": "tea"},
        target_id=record_id,
        source_guid=f"guid-{record_id}",
        cache_points=(),
    )


def _answer(record_id: str) -> None:
    service = ExpectationService(NEVER_MET, repair="auto", max_iterations=2)
    OnlineStrategy(expectation_service=service).invoke(_task(record_id), _context())


def test_each_record_starts_at_the_first_attempt(attempts):
    _answer("r1")
    _answer("r2")

    assert attempts == [1, 2, 1, 2]


def test_a_record_answered_again_goes_on_from_its_own_count(attempts):
    _answer("r1")
    _answer("r2")
    _answer("r1")

    assert attempts == [1, 2, 1, 2, 3, 4]


@pytest.fixture
def new_run():
    """Start a run as the coordinator does: a new event id for the run."""
    manager = get_manager()
    previous = manager.get_context("correlation_id")
    yield lambda run_id: manager.set_context(correlation_id=run_id)
    manager.set_context(correlation_id=previous)


def test_each_run_starts_every_record_at_the_first_attempt(attempts, new_run):
    new_run("run-1")
    _answer("r1")
    _answer("r2")
    new_run("run-2")
    _answer("r1")
    _answer("r2")

    assert attempts == [1, 2, 1, 2, 1, 2, 1, 2]
