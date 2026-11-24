"""A sandbox scenario file is read strictly, once, before any call.

An unknown key, an action the workflow does not run on the mock, an unknown error kind or
rule type, a rate outside [0, 1], a ``heal_on_attempt`` below 2 and a latency range with
min above max are each refused with the file and the key named.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.agac import scenario as sc

ACTIONS = ["extract", "classify", "vote_1", "vote_2"]


def _write(tmp_path: Path, text: str, name: str = "sandbox.yml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, text: str) -> sc.Scenario:
    _write(tmp_path, text)
    return sc.load(None, tmp_path, ACTIONS)


def _refused(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigurationError) as caught:
        _load(tmp_path, text)
    return str(caught.value)


FULL = """
seed: 42
defaults:
  latency_ms: [20, 120]
  judge: {pass_rate: 0.5}
  errors: {rate: 0.1, kinds: [timeout], heal_on_attempt: 3}
  break_rules: {rules: all, rate: 0.2, heal_on_attempt: 2}
actions:
  extract:
    break_rules: {rules: [matches_regex], rate: 0.3, heal_on_attempt: 2}
    errors: {rate: 0.05, kinds: [rate_limit, timeout, refusal, truncated, empty]}
  classify:
    pin: {label: urgent}
  vote:
    latency_ms: 5
records:
  - match: {source.page_id: p3}
    actions: {extract: {error: refusal}}
batch:
  polls_until_complete: 2
  complete_after_seconds: 1.5
  drop_rate: 0.1
  fail: [classify]
"""


def test_a_full_file_is_read(tmp_path):
    scenario = _load(tmp_path, FULL)

    assert scenario.name == "sandbox.yml"
    assert scenario.seed == 42
    assert scenario.batch.polls_until_complete == 2
    assert scenario.batch.complete_after_seconds == 1.5
    assert scenario.batch.fail == ["classify"]
    extract = scenario.rules_for("extract", {})
    assert extract.errors.kinds == ["rate_limit", "timeout", "refusal", "truncated", "empty"]
    assert extract.errors.heal_on_attempt is None
    assert extract.break_rules.rules == ["matches_regex"]
    assert extract.latency_ms == (20, 120)
    assert extract.pass_rate == 0.5
    assert scenario.rules_for("classify", {}).pin == {"label": "urgent"}


def test_a_version_base_name_names_each_version(tmp_path):
    scenario = _load(tmp_path, FULL)

    assert scenario.rules_for("vote_1", {}).latency_ms == (5, 5)
    assert scenario.rules_for("vote_2", {}).latency_ms == (5, 5)


def test_no_file_is_the_happy_preset(tmp_path):
    scenario = sc.load(None, tmp_path, ACTIONS)

    assert scenario.name == "happy"
    rules = scenario.rules_for("extract", {})
    assert rules.errors.rate == 0 and rules.break_rules.rate == 0 and rules.pass_rate == 1
    assert scenario.batch.drop_rate == 0 and scenario.batch.complete_after_seconds == 0


def test_the_chaos_preset_heals_every_fault(tmp_path):
    scenario = sc.load("chaos", tmp_path, ACTIONS)

    rules = scenario.rules_for("extract", {})
    assert scenario.name == "chaos"
    assert rules.errors.rate == 0.1 and rules.errors.heal_on_attempt == 2
    assert rules.errors.kinds == ["rate_limit", "timeout", "truncated", "empty"]
    assert rules.break_rules.rules == "all" and rules.break_rules.heal_on_attempt == 2
    assert rules.pass_rate == 0.7
    assert scenario.batch.polls_until_complete == 1 and scenario.batch.drop_rate == 0.1


def test_a_preset_is_chosen_over_the_project_file(tmp_path):
    _write(tmp_path, "seed: 7\n")

    assert sc.load("happy", tmp_path, ACTIONS).seed == 0


def test_a_path_is_read_from_where_it_points(tmp_path):
    path = _write(tmp_path, "seed: 9\n", name="other.yml")

    scenario = sc.load(str(path), tmp_path / "elsewhere", ACTIONS)

    assert scenario.seed == 9
    assert scenario.name == str(path)


def test_a_path_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(ConfigurationError, match=r"no scenario file .*missing\.yml"):
        sc.load(str(tmp_path / "missing.yml"), tmp_path, ACTIONS)


@pytest.mark.parametrize(
    ("text", "key", "why"),
    [
        ("sede: 1\n", "sede", "unknown key"),
        (
            "actions:\n  extract:\n    errorz: {rate: 0.1}\n",
            "actions.extract.errorz",
            "unknown key",
        ),
        ("batch:\n  drop: 0.1\n", "batch.drop", "unknown key"),
        (
            "actions:\n  extract:\n    errors: {kinds: [explode]}\n",
            "actions.extract.errors.kinds",
            "unknown error kind 'explode'",
        ),
        ("defaults:\n  errors: {rate: 1.5}\n", "defaults.errors.rate", "between 0 and 1"),
        ("batch:\n  drop_rate: -0.1\n", "batch.drop_rate", "between 0 and 1"),
        (
            "defaults:\n  break_rules: {heal_on_attempt: 1}\n",
            "defaults.break_rules.heal_on_attempt",
            "at least 2",
        ),
        ("defaults:\n  latency_ms: [50, 10]\n", "defaults.latency_ms", "min 50 is above max 10"),
        ("actions:\n  summarise: {latency_ms: 1}\n", "actions.summarise", "no LLM action"),
        (
            "records:\n  - match: {a: 1}\n    actions: {nope: {error: refusal}}\n",
            "records.0.actions.nope",
            "no LLM action",
        ),
        ("batch:\n  fail: [nope]\n", "batch.fail", "no LLM action"),
        (
            "actions:\n  extract:\n    break_rules: {rules: [matches_regx]}\n",
            "actions.extract.break_rules.rules",
            "unknown rule type 'matches_regx'",
        ),
        ("records:\n  - actions: {extract: {pin: {a: 1}}}\n", "records.0.match", "Field required"),
    ],
)
def test_a_bad_entry_is_refused_naming_the_file_and_key(tmp_path, text, key, why):
    message = _refused(tmp_path, text)

    assert "sandbox.yml" in message, message
    assert key in message, message
    assert why in message, message


def test_every_problem_is_named_at_once(tmp_path):
    message = _refused(tmp_path, "sede: 1\nbatch:\n  drop: 1\n")

    assert "sede" in message and "batch.drop" in message, message


def test_a_file_that_is_not_a_mapping_is_refused(tmp_path):
    assert "a mapping" in _refused(tmp_path, "- 1\n- 2\n")


def test_a_file_that_is_not_yaml_is_refused(tmp_path):
    assert "sandbox.yml" in _refused(tmp_path, "seed: [1\n")
