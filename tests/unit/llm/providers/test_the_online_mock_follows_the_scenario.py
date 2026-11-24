"""The online mock follows the loaded sandbox scenario.

A judge's side call, which names no record, passes at ``judge.pass_rate``. A call that
names a record waits its ``latency_ms`` first. With no scenario loaded the mock answers
as it always does.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.config import sandbox
from agent_actions.expectations.judge import build_judge_prompt
from agent_actions.llm.providers.agac import client as client_module
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.utils.constants import RECORD_GUID_KEY

PROMPTS = [build_judge_prompt("is calm", f"value {n}", None) for n in range(12)]


def _verdicts(tmp_path, scenario: str | None) -> list[bool]:
    config = {"name": "extract", "json_mode": False, "model_name": "m"}
    if scenario is None:
        return [
            json.loads(AgacClient.invoke(config, prompt, "", None)[0]["raw_response"])["passed"]
            for prompt in PROMPTS
        ]
    (tmp_path / "sandbox.yml").write_text(scenario)
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, ["extract"])
        return _verdicts(tmp_path, None)


def test_a_judge_passes_by_default_in_a_sandbox(tmp_path):
    assert set(_verdicts(tmp_path, "seed: 1\n")) == {True}


def test_a_judge_fails_at_a_pass_rate_of_zero(tmp_path):
    assert set(_verdicts(tmp_path, "defaults:\n  judge: {pass_rate: 0.0}\n")) == {False}


def test_outside_a_sandbox_the_judge_gets_both_verdicts(tmp_path):
    assert set(_verdicts(tmp_path, None)) == {True, False}


@pytest.mark.parametrize(("named", "waits"), [(True, [0.25]), (False, [])])
def test_a_call_that_names_a_record_waits_its_latency(tmp_path, monkeypatch, named, waits):
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    (tmp_path / "sandbox.yml").write_text("defaults:\n  latency_ms: 250\n")
    config = {"name": "extract", "json_mode": True, "model_name": "m"}
    if named:
        config[RECORD_GUID_KEY] = "g-1"

    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, ["extract"])
        AgacClient.invoke(config, "Sum up.", {"source": {"text": "a"}}, None)

    assert slept == waits
