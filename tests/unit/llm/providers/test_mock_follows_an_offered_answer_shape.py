"""In text mode the mock answers in the shape a prompt's last line offers.

A prompt that ends with two or more JSON objects joined by ` or ` gets one of them back,
chosen by the mock's seeded RNG, with each string value replaced by a generated sentence.
So an `llm_judge` on `agac-provider` gets a verdict it can read, and both verdicts occur.
Any other prompt keeps getting prose.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agent_actions.expectations.judge import build_judge_prompt, invoke_judge
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.output.response.response_builder import ResponseBuilder

CONFIG = {"json_mode": False, "name": "a"}


@pytest.fixture(autouse=True)
def _fresh_mock():
    AgacClient.reset()
    yield
    AgacClient.reset()


def _answer(prompt: str) -> str:
    return ResponseBuilder.unwrap(AgacClient.invoke(dict(CONFIG), prompt, "", None), CONFIG)


def test_a_judge_prompt_gets_a_verdict_object():
    verdict = json.loads(_answer(build_judge_prompt("r", "v", None)))

    assert set(verdict) == {"passed", "reason"}
    assert isinstance(verdict["passed"], bool)
    assert isinstance(verdict["reason"], str) and verdict["reason"].strip()


def test_both_offered_verdicts_are_reachable():
    passed = {
        json.loads(_answer(build_judge_prompt("rule", f"value {i}", None)))["passed"]
        for i in range(20)
    }

    assert passed == {True, False}


def test_one_prompt_gets_one_answer_in_two_processes():
    script = (
        "import json\n"
        "from agent_actions.expectations.judge import build_judge_prompt\n"
        "from agent_actions.llm.providers.agac.client import AgacClient\n"
        "c = {'json_mode': False, 'name': 'a'}\n"
        "print(AgacClient.invoke(c, build_judge_prompt('r', 'v', None), '', None))\n"
    )
    runs = [
        subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        for _ in range(2)
    ]

    assert runs[0].stdout.strip()
    assert runs[0].stdout == runs[1].stdout


def test_a_prompt_ending_in_prose_gets_prose():
    with pytest.raises(json.JSONDecodeError):
        json.loads(_answer("Describe the weather.\nAnswer in one paragraph."))


def test_two_offered_objects_get_one_of_them_back():
    answer = json.loads(_answer('Pick one.\n{"a": 1} or {"b": 2}'))

    assert answer in ({"a": 1}, {"b": 2})


def test_a_prompt_ending_in_one_rendered_record_gets_prose():
    with pytest.raises(json.JSONDecodeError):
        json.loads(_answer('Summarise this record.\n{"title": "x", "body": "y"}'))


@pytest.mark.parametrize(
    "last_line",
    [
        '{"a": 1} and {"b": 2}',
        '{"a": 1} or',
        '[{"a": 1}]',
        'Reply with {"a": 1}',
        'Reply with {"a": 1} or {"b": 2}',
        '{"a": 1} or {"b": 2} please',
    ],
)
def test_a_last_line_that_is_not_only_offered_objects_gets_prose(last_line):
    with pytest.raises(json.JSONDecodeError):
        json.loads(_answer(f"Do the thing.\n{last_line}"))


def test_a_judge_on_the_mock_returns_a_verdict_not_a_parse_failure():
    passed, reason = invoke_judge(
        {"model_vendor": "agac-provider", "model_name": "mock"}, "rule", "value"
    )

    assert isinstance(passed, bool)
    assert reason.strip()
    assert "not a verdict object" not in reason


def _verdict(value: str) -> bool:
    passed, _ = invoke_judge(
        {"model_vendor": "agac-provider", "model_name": "mock", "name": "act"}, "rule", value
    )
    return passed


def test_a_verdict_does_not_depend_on_the_judge_calls_before_it():
    first = _verdict("target")
    for i in range(7):
        _verdict(f"other {i}")

    assert _verdict("target") == first
    assert {_verdict("target") for _ in range(6)} == {first}


def test_the_order_of_values_does_not_change_their_verdicts():
    values = [f"value {i}" for i in range(8)]
    forward = {v: _verdict(v) for v in values}
    AgacClient.reset()
    backward = {v: _verdict(v) for v in reversed(values)}

    assert forward == backward
    assert set(forward.values()) == {True, False}
