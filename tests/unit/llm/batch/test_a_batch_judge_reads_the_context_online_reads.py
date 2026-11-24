"""A judged rule's `context:` refs reach the judge in batch as they reach it online.

Online resolves the refs against the record's LLM context. Batch judges after the
answers return, from the context map, which kept none of it, so the rule was refused
under `run_mode: batch`. Each record here is prepared for real in both modes; batch then
runs pass by pass against a provider that records each judge request.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import get_task_preparer
from agent_actions.utils import deep_json

from .judge_batch_world import INVOKE, JudgingProvider, Run, _write, verdict

ACTION = "author"
BODIES = {"r1": "cats purr", "r2": "dogs bark"}
RULE = {
    "id": "grounded",
    "type": "llm_judge",
    "field": "summary",
    "params": {"rule": "The summary is supported by the body.", "context": ["extract.body"]},
}


def _config(repair: str = "none", rule: dict[str, Any] = RULE, **expect: Any) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "model_vendor": "openai",
        "model_name": "test-model",
        "json_mode": False,
        "run_mode": "batch",
        "prompt": "Summarise {{ extract.body }}",
        "dependencies": ["extract"],
        "context_scope": {"observe": ["extract.body", "extract.title"]},
        "expect": {"expectations": [rule], "repair": repair, **expect},
    }


def _rows(bodies: dict[str, str] = BODIES) -> list[dict[str, Any]]:
    return [
        {
            "target_id": cid,
            "source_guid": f"sg-{cid}",
            "content": {"extract": {"body": body, "title": f"title of {cid}"}},
        }
        for cid, body in bodies.items()
    ]


def _context_map(config: dict[str, Any], bodies: dict[str, str] = BODIES) -> dict[str, Any]:
    """What a real preparation stores for the records, read back as a later run reads it."""
    provider = MagicMock()
    provider.prepare_tasks.return_value = []
    prepared = BatchTaskPreparator(
        action_indices={"extract": 0, ACTION: 1}, dependency_configs={}
    ).prepare_tasks(agent_config=config, data=_rows(bodies), provider=provider)
    assert set(prepared.context_map) == set(bodies)
    return deep_json.loads(deep_json.dumps(prepared.context_map))


def _online_llm_context(config: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    context = PreparationContext(
        agent_config=config,
        agent_name=ACTION,
        is_first_stage=False,
        mode=RunMode.ONLINE,
        agent_indices={"extract": 0, ACTION: 1},
        dependency_configs={},
    )
    return get_task_preparer().prepare(dict(row), context).llm_context


def _grounded(prompt: str, _vote: int = 0) -> str:
    """A judge that passes a value only when its grounding context holds it."""
    section = re.search(
        r"## Grounding context\n(.*?)\n\n## Value under test\n(.*?)\n\n", prompt, re.S
    )
    if section is None:
        return verdict(False, "no grounding context")
    passed = section.group(2) in section.group(1)
    return verdict(passed, "in the body" if passed else "not in the body")


def _online(config: dict[str, Any], answers: dict[str, dict[str, Any]], bodies=BODIES):
    """Each record's judge prompts and outcome, through one service as an online action runs."""
    prompts: list[str] = []

    def reply(**kwargs):
        prompts.append(kwargs["prompt_config"])
        return [{"raw_response": _grounded(kwargs["prompt_config"])}]

    service = create_expectation_service_from_config(
        config["expect"], action_name=ACTION, agent_config=config
    )
    outcomes = {}
    with patch(INVOKE, side_effect=reply):
        for row in _rows(bodies):
            llm_context = _online_llm_context(config, row)
            (outcome,) = service.validate(answers[row["target_id"]], llm_context).outcomes
            outcomes[row["target_id"]] = (outcome.passed, outcome.detail)
    return prompts, outcomes


def _results(answers: dict[str, dict[str, Any]]) -> list[BatchResult]:
    return [
        BatchResult(custom_id=cid, content=answer, success=True) for cid, answer in answers.items()
    ]


def _batch(config: dict[str, Any], answers: dict[str, dict[str, Any]], bodies=BODIES, repair=None):
    """The judge requests each judge batch carried, and each record's shipped outcome."""
    provider = JudgingProvider(_grounded, repair)
    run = Run(config, provider)
    run.context_map.update(_context_map(config, bodies))
    results = _results(answers)
    wrote = run.main_batch_returns(results)
    for _ in range(6):
        if wrote or run.live_entry() is None:
            break
        # Each pass is a later run: it has the context map as it was stored, nothing else.
        run.context_map = deep_json.loads(deep_json.dumps(run.context_map))
        wrote = run.recovery_batch_returns() is not None
    assert run.online == [], "the batch path called the judge online"
    # A pass that sent nothing leaves the write to its caller.
    shipped_by_id = (
        run.verdicts() if run.finalized else _write(run.config, results, run.context_map)
    )
    outcomes = {}
    for cid, shipped in shipped_by_id.items():
        (outcome,) = shipped["outcomes"]
        outcomes[cid] = (outcome["passed"], outcome["detail"])
    return provider, outcomes


def _judge_prompts(provider: JudgingProvider) -> list[str]:
    return [
        task["body"]["messages"][0]["content"]
        for tasks in provider._tasks.values()
        for task in tasks
        if task["custom_id"].startswith("j_")
    ]


ANSWERS = {"r1": {"summary": "cats purr"}, "r2": {"summary": "cats purr"}}
# r1's summary is in its own body; r2's is not, and each has a different value under test.
DISTINCT = {"r1": {"summary": "cats purr"}, "r2": {"summary": "birds sing"}}


@pytest.mark.parametrize("repair", ["none", "retry"])
def test_the_judge_request_is_the_prompt_online_sends_for_the_record(repair):
    config = _config(repair, max_iterations=1)

    online_prompts, online = _online(config, DISTINCT)
    provider, batch = _batch(config, DISTINCT)

    assert _judge_prompts(provider) == online_prompts
    assert "## Grounding context\n- extract.body: cats purr\n" in online_prompts[0]
    assert "## Grounding context\n- extract.body: dogs bark\n" in online_prompts[1]
    assert batch == online
    assert [passed for passed, _ in batch.values()] == [True, False]


def test_only_the_values_the_rules_reference_are_kept_for_the_record():
    context_map = _context_map(_config())

    assert context_map["r1"][ContextMetaKeys.JUDGE_CONTEXT] == {"extract": {"body": "cats purr"}}
    assert ContextMetaKeys.JUDGE_CONTEXT in ContextMetaKeys.all_internal_keys()


def test_an_action_whose_rules_reference_nothing_keeps_nothing():
    rule = {**RULE, "params": {"rule": RULE["params"]["rule"]}}

    assert ContextMetaKeys.JUDGE_CONTEXT not in _context_map(_config(rule=rule))["r1"]


def test_a_reference_the_action_does_not_observe_fails_as_online_fails_it():
    rule = {**RULE, "params": {**RULE["params"], "context": ["extract.body", "extract.notes"]}}
    config = _config(rule=rule)

    _prompts, online = _online(config, DISTINCT)
    provider, batch = _batch(config, DISTINCT)

    assert batch == online
    assert batch["r1"] == (
        False,
        "context reference 'extract.notes' is not present in llm_context",
    )
    assert provider.batches == [], "a rule that cannot resolve its context sends no judge request"


def test_one_value_under_two_contexts_is_judged_once_as_online_judges_it():
    """The judge cache keys on the rule and the value, not the context, in both modes."""
    config = _config()

    online_prompts, online = _online(config, ANSWERS)
    provider, batch = _batch(config, ANSWERS)

    assert len(online_prompts) == 1
    assert _judge_prompts(provider) == online_prompts
    assert batch == online
    assert batch["r2"] == batch["r1"] == (True, "in the body")


def test_a_repair_round_is_judged_against_the_record_s_context_too():
    config = _config("retry", max_iterations=2)

    provider, batch = _batch(config, DISTINCT, repair=lambda _cid: {"summary": "dogs bark"})

    assert [name for name, _ in provider.batches] == [
        "f.json_judge_1",
        "f.json_repair_1",
        "f.json_judge_2",
    ]
    assert _judge_prompts(provider)[-1].count("- extract.body: dogs bark\n") == 1
    assert batch == {"r1": (True, "in the body"), "r2": (True, "in the body")}


def test_judge_mode_online_hands_the_online_judge_the_context_too():
    config = _config(judge_mode="online")
    prompts: list[str] = []

    def reply(**kwargs):
        prompts.append(kwargs["prompt_config"])
        return [{"raw_response": _grounded(kwargs["prompt_config"])}]

    with patch(INVOKE, side_effect=reply):
        shipped = _write(config, _results(DISTINCT), _context_map(config))

    assert prompts == _online(config, DISTINCT)[0]
    assert [v["overall_pass"] for v in shipped.values()] == [True, False]
