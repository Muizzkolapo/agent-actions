"""A sandbox scenario stubs a tool action by name, and only where the mock can build it.

``stub`` is a key of a tool action under ``actions``. The load refuses it anywhere else,
on a tool the mock cannot build an output for, and refuses on a tool action each key that
describes a model call. ``pin`` on a tool action needs ``stub: true``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.agac import scenario as sc

LLM_ACTIONS = {"extract": None, "vote_1": "vote", "vote_2": "vote"}
TOOLS = {
    "search": sc.Tool(),
    "plain": sc.Tool(cannot_stub="has no output schema"),
    "merge": sc.Tool(cannot_stub="has granularity File"),
    "fetch_1": sc.Tool(group="fetch"),
    "fetch_2": sc.Tool(group="fetch"),
}


def _load(tmp_path: Path, text: str) -> sc.Scenario:
    (tmp_path / "sandbox.yml").write_text(text, encoding="utf-8")
    return sc.load(None, tmp_path, LLM_ACTIONS, tools=TOOLS)


def _refused(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigurationError) as caught:
        _load(tmp_path, text)
    assert caught.value.context["config_file"] == "sandbox.yml"
    return str(caught.value)


def test_a_tool_action_is_stubbed_by_name(tmp_path):
    scenario = _load(tmp_path, "actions:\n  search: {stub: true}\n")

    assert scenario.stubs("search")
    assert scenario.stubbed() == ["search"]
    assert not scenario.stubs("plain") and not scenario.stubs("extract")


def test_a_stubbed_tool_takes_a_pin_and_a_pin_for_a_matched_record(tmp_path):
    scenario = _load(
        tmp_path,
        "actions:\n  search: {stub: true, pin: {source: stubbed}}\n"
        "records:\n  - match: {source.title: Dune}\n"
        "    actions: {search: {pin: {total_found: 0}}}\n",
    )

    assert scenario.rules_for("search", {"source": {"title": "Emma"}}).pin == {"source": "stubbed"}
    assert scenario.rules_for("search", {"source": {"title": "Dune"}}).pin == {"total_found": 0}


def test_a_tool_action_named_with_no_stub_runs_its_own_code(tmp_path):
    scenario = _load(tmp_path, "actions:\n  search: {}\n  plain: {stub: false}\n")

    assert scenario.stubbed() == []


def test_a_version_base_name_stubs_each_version(tmp_path):
    scenario = _load(tmp_path, "actions:\n  fetch: {stub: true}\n")

    assert scenario.stubbed() == ["fetch_1", "fetch_2"]


def test_an_entry_for_one_version_wins_over_its_base_name(tmp_path):
    scenario = _load(tmp_path, "actions:\n  fetch: {stub: true}\n  fetch_2: {stub: false}\n")

    assert scenario.stubbed() == ["fetch_1"]


@pytest.mark.parametrize("preset", ["happy", "chaos"])
def test_a_preset_stubs_nothing(tmp_path, preset):
    scenario = sc.load(preset, tmp_path, LLM_ACTIONS, tools=TOOLS)

    assert scenario.stubbed() == []


@pytest.mark.parametrize(
    ("text", "key", "why"),
    [
        ("actions:\n  extract: {stub: true}\n", "actions.extract.stub", "is not a tool action"),
        ("actions:\n  vote: {stub: false}\n", "actions.vote.stub", "is not a tool action"),
        (
            "actions:\n  plain: {stub: true}\n",
            "actions.plain.stub",
            "tool action 'plain' has no output schema",
        ),
        (
            "actions:\n  merge: {stub: true}\n",
            "actions.merge.stub",
            "tool action 'merge' has granularity File",
        ),
        (
            "actions:\n  search: {stub: true, errors: {rate: 0.5}}\n",
            "actions.search.errors",
            "describes a model call",
        ),
        (
            "actions:\n  search: {break_rules: {rate: 0.5}}\n",
            "actions.search.break_rules",
            "describes a model call",
        ),
        (
            "actions:\n  search: {judge: {pass_rate: 0.5}}\n",
            "actions.search.judge",
            "describes a model call",
        ),
        (
            "actions:\n  fetch: {stub: true, latency_ms: 5}\n",
            "actions.fetch.latency_ms",
            "describes a model call",
        ),
        (
            "actions:\n  search: {stub: true}\n"
            "records:\n  - match: {a: 1}\n    actions: {search: {error: refusal}}\n",
            "records.0.actions.search.error",
            "describes a model call",
        ),
        (
            "actions:\n  search: {pin: {source: x}}\n",
            "actions.search.pin",
            "tool action 'search' is not stubbed",
        ),
        (
            "actions:\n  fetch: {stub: true}\n  fetch_2: {pin: {source: x}}\n",
            "actions.fetch_2.pin",
            "tool action 'fetch_2' is not stubbed",
        ),
        (
            "records:\n  - match: {a: 1}\n    actions: {search: {pin: {source: x}}}\n",
            "records.0.actions.search.pin",
            "tool action 'search' is not stubbed",
        ),
        ("defaults:\n  stub: true\n", "defaults.stub", "under actions"),
        (
            "actions:\n  search: {stub: true}\n"
            "records:\n  - match: {a: 1}\n    actions: {search: {stub: false}}\n",
            "records.0.actions.search.stub",
            "under actions",
        ),
        ("batch:\n  fail: [search]\n", "batch.fail", "'search' is a tool action"),
        (
            "actions:\n  serch: {stub: true}\n",
            "actions.serch",
            "its tool actions: search, plain, merge, fetch_1, fetch_2",
        ),
    ],
)
def test_a_stub_the_run_cannot_follow_is_refused_naming_the_file_and_key(tmp_path, text, key, why):
    message = _refused(tmp_path, text)

    assert "sandbox.yml" in message, message
    assert f"- {key}: " in message, message
    assert why in message, message


def test_a_scenario_of_llm_actions_alone_loads_with_no_tools_given(tmp_path):
    (tmp_path / "sandbox.yml").write_text("actions:\n  extract: {latency_ms: 1}\n")

    scenario = sc.load(None, tmp_path, LLM_ACTIONS)

    assert scenario.stubbed() == []
    assert not scenario.stubs("extract")
