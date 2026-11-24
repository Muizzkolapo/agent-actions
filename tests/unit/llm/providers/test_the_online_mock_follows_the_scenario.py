"""The online mock follows the loaded sandbox scenario.

A judge's side call, which names no record, passes at ``judge.pass_rate``. A call that
names a record waits its ``latency_ms`` first, matches ``records`` on its whole input and,
in text mode, fails as a real client fails. With a store attached the attempts count on
across loads. With no scenario loaded the mock answers as it always does.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from agent_actions.config import sandbox
from agent_actions.errors import NetworkError, RateLimitError, VendorAPIError
from agent_actions.expectations.judge import build_judge_prompt
from agent_actions.llm.providers.agac import client as client_module
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.faults import NOT_JSON
from agent_actions.utils.constants import RECORD_GUID_KEY, RECORD_INPUT_KEY

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
        sandbox.load_scenario(tmp_path, {"extract": None})
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
        sandbox.load_scenario(tmp_path, {"extract": None})
        AgacClient.invoke(config, "Sum up.", {"source": {"text": "a"}}, None)

    assert slept == waits


def _follow(tmp_path, scenario: str):
    (tmp_path / "sandbox.yml").write_text(scenario)
    stack = contextlib.ExitStack()
    stack.enter_context(sandbox.sandbox_mode(True))
    stack.enter_context(sandbox.scenario_choice(None))
    sandbox.load_scenario(tmp_path, {"extract": None})
    return stack


def _text_call(page: str, attempt_record: str = "g-1") -> str:
    config = {
        "name": "extract",
        "json_mode": False,
        "model_name": "m",
        RECORD_GUID_KEY: attempt_record,
        RECORD_INPUT_KEY: {"source": {"page_id": page}},
    }
    return AgacClient.invoke(config, "Write about the page.", {}, None)[0]["raw_response"]


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("rate_limit", RateLimitError),
        ("timeout", NetworkError),
        ("server_error", NetworkError),
        ("refusal", VendorAPIError),
        ("empty", VendorAPIError),
    ],
)
def test_a_text_mode_call_raises_the_fault_a_real_client_raises(tmp_path, kind, error):
    with _follow(tmp_path, f"defaults:\n  errors: {{rate: 1.0, kinds: [{kind}]}}\n"):
        with pytest.raises(error):
            _text_call("p1")
        assert sandbox.scenario_summary().startswith("SANDBOX scenario sandbox.yml: 1 errors")


def test_a_cut_off_text_mode_answer_is_the_first_half_of_the_honest_one(tmp_path):
    with _follow(tmp_path, "seed: 1\n"):
        honest = _text_call("p1", "g-honest")
    with _follow(tmp_path, "defaults:\n  errors: {rate: 1.0, kinds: [truncated]}\n"):
        cut = _text_call("p1", "g-cut")

    assert cut == honest[: len(honest) // 2] and cut


def test_text_that_is_not_json_is_a_text_mode_answer(tmp_path):
    with _follow(tmp_path, "defaults:\n  errors: {rate: 1.0, kinds: [invalid_json]}\n"):
        assert _text_call("p1") == NOT_JSON


def test_a_record_match_reads_the_whole_input_not_the_context_block(tmp_path):
    scenario = (
        "records:\n  - match: {source.page_id: p2}\n    actions: {extract: {error: refusal}}\n"
    )

    with _follow(tmp_path, scenario):
        assert _text_call("p1", "g-1")
        with pytest.raises(VendorAPIError):
            _text_call("p2", "g-2")


def test_with_a_store_the_count_of_attempts_goes_on_in_the_next_load(tmp_path):
    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

    scenario = "defaults:\n  errors: {rate: 1.0, kinds: [refusal], heal_on_attempt: 3}\n"
    outcomes = []
    for _ in range(3):
        store = SQLiteBackend.create(db_path=str(tmp_path / "wf.sandbox.db"), workflow_name="wf")
        store.initialize()
        with _follow(tmp_path, scenario):
            sandbox.attach_store(store)
            try:
                outcomes.append(bool(_text_call("p1")))
            except VendorAPIError:
                outcomes.append(False)

    assert outcomes == [False, False, True]
