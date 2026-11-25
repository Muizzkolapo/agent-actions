"""A tool action the sandbox scenario stubs does not run; the mock builds its output.

The output meets the tool's output schema and its expectation rules, copies an observed
input field of the same name, and takes the scenario's ``pin``. It is seeded with the
action and the record's input, so one input gets one output in every run and thread.
With no ``stub``, and outside a sandbox run, the tool's own code runs.
"""

from __future__ import annotations

import contextlib
import threading

import jsonschema
import pytest

from agent_actions.config import sandbox
from agent_actions.errors import SchemaValidationError
from agent_actions.llm.providers.agac.scenario import Tool
from agent_actions.llm.providers.tools import client as client_module
from agent_actions.llm.providers.tools.client import ToolClient
from agent_actions.utils.constants import RECORD_GUID_KEY, RECORD_INPUT_KEY

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "shelf": {"type": "string"},
        "tone": {"type": "string"},
        "total_found": {"type": "integer", "minimum": 0, "maximum": 50},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"isbn": {"type": "string"}, "score": {"type": "number"}},
                "required": ["isbn", "score"],
            },
        },
    },
    "required": ["title", "shelf", "tone", "total_found", "matches"],
    "additionalProperties": False,
}
RULES = [
    {
        "id": "shelf_shape",
        "type": "matches_regex",
        "field": "shelf",
        "params": {"pattern": "^[A-Z]{2}-[0-9]{3}$"},
    },
    {
        "id": "tone_is_known",
        "type": "accepted_values",
        "field": "tone",
        "params": {"values": ["calm", "stormy"]},
    },
]
STUBBED = "actions:\n  search: {stub: true}\n"


def _config(**extra) -> dict:
    return {
        "name": "search",
        "kind": "tool",
        "model_vendor": "tool",
        "model_name": "search_catalog",
        "granularity": "Record",
        "json_output_schema": SCHEMA,
        "context_scope": {"observe": ["source.title", "source.year"]},
        "expect": {"repair": "none", "expectations": RULES},
        **extra,
    }


@pytest.fixture
def calls(monkeypatch) -> list:
    """Stands in for the tool's own code and keeps each input it was called with."""
    seen: list = []

    def run(name, data, **kwargs):
        seen.append((name, data))
        return {"title": "from the tool"}

    monkeypatch.setattr(client_module, "execute_user_defined_function", run)
    return seen


@contextlib.contextmanager
def _follow(tmp_path, scenario: str):
    (tmp_path / "sandbox.yml").write_text(scenario)
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, {}, {"search": Tool()})
        yield


def _page(title: str) -> dict:
    return {"source": {"title": title, "year": 1965}}


def test_a_stubbed_tool_does_not_run_and_its_output_meets_the_schema_and_rules(tmp_path, calls):
    with _follow(tmp_path, STUBBED):
        output = ToolClient.invoke(_config(), _page("Dune"))

    assert calls == []
    jsonschema.validate(output, SCHEMA)
    assert len(output["shelf"]) == 6 and output["shelf"][2] == "-", output
    assert output["tone"] in ("calm", "stormy")


def test_an_observed_field_of_the_same_name_is_copied_from_the_input(tmp_path, calls):
    with _follow(tmp_path, STUBBED):
        outputs = [ToolClient.invoke(_config(), _page(title)) for title in ("Dune", "Emma")]

    assert [output["title"] for output in outputs] == ["Dune", "Emma"]


def test_a_pin_sets_its_field_and_a_matched_record_takes_its_own_pin(tmp_path, calls):
    scenario = (
        "actions:\n  search: {stub: true, pin: {tone: stormy}}\n"
        "records:\n  - match: {source.title: Dune}\n"
        "    actions: {search: {pin: {total_found: 0}}}\n"
    )
    with _follow(tmp_path, scenario):
        emma = ToolClient.invoke(_config(), _page("Emma"))
        dune = ToolClient.invoke(_config(), _page("Dune"))

    assert emma["tone"] == "stormy"
    assert dune["total_found"] == 0


def test_the_whole_input_of_the_record_decides_the_match_and_the_copy(tmp_path, calls):
    scenario = (
        "actions:\n  search: {stub: true}\n"
        "records:\n  - match: {source.title: Dune}\n"
        "    actions: {search: {pin: {total_found: 7}}}\n"
    )
    config = _config(**{RECORD_INPUT_KEY: _page("Dune"), RECORD_GUID_KEY: "g-1"})
    with _follow(tmp_path, scenario):
        output = ToolClient.invoke(config, {"source": {"year": 1965}})

    assert (output["title"], output["total_found"]) == ("Dune", 7)


def test_one_input_gets_one_output_whatever_ran_before_and_in_any_thread(tmp_path, calls):
    outputs: dict[str, dict] = {}

    def other_thread() -> None:
        # Sandbox mode is one flag for the process, so the thread reads the same scenario.
        outputs["threaded"] = ToolClient.invoke(_config(), _page("Dune"))

    with _follow(tmp_path, STUBBED):
        first = ToolClient.invoke(_config(), _page("Dune"))
        emma = ToolClient.invoke(_config(), _page("Emma"))
        again = ToolClient.invoke(_config(), _page("Dune"))
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()

    assert first == again == outputs["threaded"]
    assert emma != first
    assert {key: emma[key] for key in emma if key != "title"} != {
        key: first[key] for key in first if key != "title"
    }


def test_another_tool_gets_another_output_for_the_same_input(tmp_path, calls):
    (tmp_path / "sandbox.yml").write_text(
        "actions:\n  search: {stub: true}\n  lookup: {stub: true}\n"
    )
    with sandbox.sandbox_mode(True), sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, {}, {"search": Tool(), "lookup": Tool()})
        search = ToolClient.invoke(_config(), _page("Dune"))
        lookup = ToolClient.invoke(_config(name="lookup"), _page("Dune"))

    assert search != lookup


def test_a_pinned_value_the_schema_refuses_fails_the_record_as_the_tool_s_output_would(
    tmp_path, calls
):
    with _follow(tmp_path, "actions:\n  search: {stub: true, pin: {total_found: many}}\n"):
        with pytest.raises(SchemaValidationError, match="total_found"):
            ToolClient.invoke(_config(), _page("Dune"))


@pytest.mark.parametrize("scenario", ["seed: 3\n", "actions:\n  search: {stub: false}\n"])
def test_a_tool_the_scenario_does_not_stub_runs_its_own_code(tmp_path, calls, scenario):
    with _follow(tmp_path, scenario):
        output = ToolClient.invoke(_config(), _page("Dune"))

    assert output == {"title": "from the tool"}
    assert calls == [("search_catalog", _page("Dune"))]


def test_outside_a_sandbox_run_the_stub_is_not_read(tmp_path, calls):
    (tmp_path / "sandbox.yml").write_text(STUBBED)
    with sandbox.scenario_choice(None):
        sandbox.load_scenario(tmp_path, {}, {"search": Tool()})
        output = ToolClient.invoke(_config(), _page("Dune"))

    assert output == {"title": "from the tool"}
    assert len(calls) == 1


def test_a_stubbed_call_counts_as_a_call_the_mock_answered(tmp_path, calls):
    with _follow(tmp_path, STUBBED):
        assert sandbox.scenario_summary(only_after_calls=True) is None
        ToolClient.invoke(_config(), _page("Dune"))

        assert sandbox.scenario_summary(only_after_calls=True) == (
            "SANDBOX scenario sandbox.yml: 0 errors, 0 rules broken, 0 batch results dropped"
        )
