"""A workflow written as a list of agent entries is held to the same granularity rule.

That format skips the expander, so its entries are checked where they are loaded: an
LLM agent cannot run at FILE granularity, and a HITL agent cannot run per record.
"""

from __future__ import annotations

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError

MODEL = {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "k"}


def _agents(entry: dict, *, nested: bool = False) -> list[dict]:
    manager = ConfigManager("wf.yml", "")
    entries = [{"agent_type": "label_page", **entry}]
    manager.user_config = {"wf": {"agents": entries} if nested else entries}
    manager.agent_name = "wf"
    return manager.get_user_agents()


@pytest.mark.parametrize("nested", [False, True], ids=["list", "agents_key"])
def test_an_llm_agent_at_file_granularity_is_refused(nested):
    with pytest.raises(ConfigurationError, match="FILE granularity is only supported") as refused:
        _agents({**MODEL, "granularity": "file"}, nested=nested)

    assert refused.value.context == {"agent_name": "label_page"}


def test_a_hitl_agent_at_record_granularity_is_refused():
    with pytest.raises(ConfigurationError, match="HITL actions require FILE granularity"):
        _agents({"kind": "hitl", "model_vendor": "hitl", "granularity": "record"})


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "tool", "model_vendor": "tool", "granularity": "file"},
        {"model_vendor": "tool", "granularity": "file"},
        {"kind": "hitl", "model_vendor": "hitl", "granularity": "file"},
        {**MODEL, "granularity": "record"},
        MODEL,
    ],
    ids=["tool_kind", "tool_vendor", "hitl_file", "llm_record", "llm_unset"],
)
def test_an_agent_its_kind_can_run_is_returned_as_written(entry):
    (agent,) = _agents(entry)

    assert agent == {"agent_type": "label_page", **entry}
