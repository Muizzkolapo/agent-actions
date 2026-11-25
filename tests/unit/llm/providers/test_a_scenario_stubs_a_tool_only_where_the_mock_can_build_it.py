"""A sandbox scenario stubs a tool action by name, and only where the mock can build it.

``stub`` is a key of a tool action under ``actions``. The load refuses it anywhere else,
on a tool the mock cannot build an output for, and refuses on a tool action each key that
describes a model call. ``pin`` on a tool action needs ``stub: true``. ``stub`` is
``true`` or ``false``: a string or a number is refused, not read as a boolean. A preset
keeps each project-file entry that sets ``stub``, and refuses any key but ``stub`` and
``pin`` there as a run without a preset does.
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


@pytest.mark.parametrize(("value", "stubbed"), [("true", ["search"]), ("false", [])])
def test_stub_takes_true_or_false(tmp_path, value, stubbed):
    scenario = _load(tmp_path, f"actions:\n  search: {{stub: {value}}}\n")

    assert scenario.stubbed() == stubbed


@pytest.mark.parametrize("value", ['"yes"', '"true"', "1", "0"])
def test_stub_that_is_not_a_boolean_is_refused_naming_the_file_and_key(tmp_path, value):
    message = _refused(tmp_path, f"actions:\n  search: {{stub: {value}}}\n")

    assert "sandbox.yml" in message, message
    assert "- actions.search.stub: Input should be a valid boolean" in message, message


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


def _under_a_preset(tmp_path: Path, text: str, preset: str = "happy") -> sc.Scenario:
    (tmp_path / "sandbox.yml").write_text(text, encoding="utf-8")
    return sc.load(preset, tmp_path, LLM_ACTIONS, tools=TOOLS)


@pytest.mark.parametrize(
    ("entry", "key"),
    [
        ("{stub: true, errors: {rate: 0.5}}", "errors"),
        ("{stub: true, break_rules: {rate: 0.5}}", "break_rules"),
        ("{stub: true, judge: {pass_rate: 0.5}}", "judge"),
        ("{stub: true, latency_ms: 5}", "latency_ms"),
    ],
)
def test_a_preset_refuses_a_model_call_key_in_a_kept_entry(tmp_path, entry, key):
    with pytest.raises(ConfigurationError) as caught:
        _under_a_preset(tmp_path, f"actions:\n  search: {entry}\n", "chaos")

    message = str(caught.value)
    assert "Scenario preset chaos with the stubs of sandbox.yml has 1 problem(s)" in message
    assert (
        f"- actions.search.{key}: 'search' is a tool action, and {key} describes a model call"
        in message
    )


def test_a_preset_refuses_error_in_a_kept_entry_as_a_run_without_one_does(tmp_path):
    text = "actions:\n  search: {stub: true, error: refusal}\n"
    without = _refused(tmp_path, text)

    with pytest.raises(ConfigurationError) as caught:
        _under_a_preset(tmp_path, text)

    assert "- actions.search.error: unknown key" in without, without
    assert "- actions.search.error: unknown key" in str(caught.value), str(caught.value)
    assert "preset happy with the stubs of sandbox.yml" in str(caught.value)


def test_a_preset_refuses_an_unknown_key_in_a_kept_entry_as_a_run_without_one_does(tmp_path):
    text = "actions:\n  search: {stub: true, bogus: 1}\n"
    without = _refused(tmp_path, text)

    with pytest.raises(ConfigurationError) as caught:
        _under_a_preset(tmp_path, text, "chaos")

    assert "- actions.search.bogus: unknown key" in without, without
    assert "- actions.search.bogus: unknown key" in str(caught.value), str(caught.value)
    assert "preset chaos with the stubs of sandbox.yml" in str(caught.value)


def test_a_preset_keeps_only_the_stub_and_pin_of_a_kept_entry(tmp_path):
    scenario = _under_a_preset(
        tmp_path,
        "defaults: {errors: {rate: 1}, bogus: 1}\n"
        "actions:\n  search: {stub: true, pin: {source: x}}\n"
        "  extract: {latency_ms: -1}\n"
        "records: not a list\n",
    )

    assert scenario.stubbed() == ["search"]
    assert scenario.rules_for("search", {}).pin == {"source": "x"}
    assert scenario.rules_for("extract", {}).errors.rate == 0.0


def test_a_preset_ignores_an_entry_without_stub(tmp_path):
    scenario = _under_a_preset(
        tmp_path, "actions:\n  extract: {latency_ms: 5, errors: {rate: 1}}\n"
    )

    assert scenario.stubs_from is None
    assert scenario.rules_for("extract", {}).errors.rate == 0.0


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
