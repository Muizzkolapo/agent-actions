"""A call's config holds the record's whole input only while a sandbox scenario is followed.

The scenario's mock reads it to match ``records`` and to key its decisions. A call to a
real vendor, and a sandbox read command, follow no scenario, so their config holds the
names of the record and nothing of its input.
"""

from __future__ import annotations

from unittest.mock import patch

from agent_actions.config import sandbox
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.utils.constants import RECORD_GUID_KEY, RECORD_ID_KEY, RECORD_INPUT_KEY

CONFIG = {
    "model_vendor": "openai",
    "model_name": "gpt-4o-mini",
    "kind": "llm",
    "granularity": "record",
}
INPUT = {"source": {"page_id": "p1", "text": "calm sea"}}


def _call_config() -> dict:
    """The config the vendor's client gets for one record's call."""
    with patch("agent_actions.llm.realtime.builder.create_dynamic_agent") as client:
        client.return_value = [{"result": "ok"}]
        run_dynamic_agent(CONFIG, "extract", INPUT, "Sum up.", record_id="r1", source_guid="g1")
    return client.call_args[0][0]


def test_a_real_vendor_call_holds_no_record_input():
    config = _call_config()

    assert RECORD_INPUT_KEY not in config
    assert (config[RECORD_ID_KEY], config[RECORD_GUID_KEY]) == ("r1", "g1")


def test_a_sandbox_command_that_follows_no_scenario_holds_no_record_input():
    with sandbox.sandbox_mode(True):
        config = _call_config()

    assert RECORD_INPUT_KEY not in config


def test_a_call_under_a_scenario_holds_the_record_input(tmp_path):
    with sandbox.sandbox_mode(True), sandbox.scenario_choice("happy"):
        sandbox.load_scenario(tmp_path, {"extract": None})
        config = _call_config()

    assert config[RECORD_INPUT_KEY] == INPUT
