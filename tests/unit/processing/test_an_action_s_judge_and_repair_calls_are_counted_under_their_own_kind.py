"""An online action's calls are counted by kind: its own, its repairs and its judge's.

The first generation of a record is a `main` call. A call the `expect:` repair loop makes
after it is a `repair` call. A call an `llm_judge` rule makes is a `judge` call, one per
vote, under the model the rule names. Each is counted where every call is counted; the
strategy and the side-call executor only say which kind is in force.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.llm.providers.usage_tracker import UsageLedger, accounting
from agent_actions.output.response.response_builder import ResponseBuilder
from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"
VOTES = 5
INVOKE = "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client"
AGENT_CONFIG = {"model_vendor": "anthropic", "model_name": "main-model"}

ENOUGH_IDEAS = {"id": "count", "type": "item_count", "field": "ideas", "params": {"min": 2}}
ON_TOPIC = {
    "id": "on_topic",
    "type": "llm_judge",
    "field": "ideas",
    "params": {"rule": "Every idea is on topic.", "votes": VOTES, "model": "judge-model"},
}


def _model_call(model: str, prompt: int, completion: int) -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=prompt, output_tokens=completion)
    )
    ResponseBuilder.record_usage_and_event(response, "anthropic", model, 1.0, "request")


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _answer_one_record(monkeypatch, backend, expect: dict[str, Any], responses: list[Any]):
    """Answer one record online; the rows its calls were counted in, by kind."""
    answered: list[str] = []

    def main_call(self, task, ctx, prompt, *_):
        answered.append(prompt)
        _model_call(ctx.agent_config["model_name"], 100, 10)
        return responses[len(answered) - 1], True

    def judge_call(**request):
        _model_call(request["agent_config"]["model_name"], 7, 1)
        return [{"raw_response": json.dumps({"passed": True, "reason": "on topic"})}]

    monkeypatch.setattr(OnlineStrategy, "_call_llm", main_call)
    service = create_expectation_service_from_config(
        expect, action_name=ACTION, agent_config=AGENT_CONFIG
    )
    context = SimpleNamespace(
        agent_name=ACTION,
        agent_config=AGENT_CONFIG,
        storage_backend=backend,
        mode=RunMode.ONLINE,
        workflow_metadata={"run_id": "run-1"},
    )
    task = SimpleNamespace(
        should_execute=True,
        is_passthrough=False,
        original_content={},
        passthrough_fields={},
        formatted_prompt="PROMPT",
        llm_context={"page": "p"},
        target_id="r1",
        source_guid="g1",
    )
    ledger = UsageLedger(ACTION)
    with accounting(ledger), patch(INVOKE, side_effect=judge_call) as judged:
        OnlineStrategy(expectation_service=service).invoke(task, context)
    return {row["kind"]: row for row in ledger.rows()}, judged.call_count


def test_the_votes_of_a_judged_rule_are_counted_as_judge_calls(monkeypatch, backend):
    """Verification 7.2: an action with `votes: 5` judge rules reports its judge calls as
    `judge`."""
    by_kind, judge_calls = _answer_one_record(
        monkeypatch,
        backend,
        {"expectations": [ON_TOPIC], "repair": "none"},
        [{"ideas": ["tides", "moons"]}],
    )

    assert judge_calls == VOTES
    assert by_kind["judge"] == {
        "kind": "judge",
        "batch": False,
        "model": "judge-model",
        "calls": VOTES,
        "input_tokens": 7 * VOTES,
        "output_tokens": VOTES,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    assert (by_kind["main"]["calls"], by_kind["main"]["model"]) == (1, "main-model")
    assert sorted(by_kind) == ["judge", "main"]


def test_a_call_the_repair_loop_makes_is_counted_as_a_repair_call(monkeypatch, backend):
    by_kind, _ = _answer_one_record(
        monkeypatch,
        backend,
        {"expectations": [ENOUGH_IDEAS], "repair": "auto", "max_iterations": 3},
        [{"ideas": ["one"]}, {"ideas": ["still one"]}, {"ideas": ["tides", "moons"]}],
    )

    assert {kind: row["calls"] for kind, row in by_kind.items()} == {"main": 1, "repair": 2}
    assert by_kind["repair"]["input_tokens"] == 200


def test_a_judge_call_made_for_a_repaired_answer_is_still_a_judge_call(monkeypatch, backend):
    by_kind, judge_calls = _answer_one_record(
        monkeypatch,
        backend,
        {"expectations": [ENOUGH_IDEAS, ON_TOPIC], "repair": "auto", "max_iterations": 3},
        [{"ideas": ["one"]}, {"ideas": ["tides", "moons"]}],
    )

    assert (by_kind["main"]["calls"], by_kind["repair"]["calls"]) == (1, 1)
    assert by_kind["judge"]["calls"] == judge_calls
    assert judge_calls >= VOTES
