"""One rule decides whether an action takes the batch path."""

import pytest

from agent_actions.config.schema import ActionKind
from agent_actions.config.types import RunMode
from agent_actions.llm.config.vendor import effective_run_mode, runs_in_batch


@pytest.mark.parametrize("run_mode", [RunMode.BATCH, "batch"])
def test_an_llm_action_under_batch_takes_the_batch_path(run_mode):
    assert runs_in_batch({"kind": "llm", "model_vendor": "openai", "run_mode": run_mode}) is True


@pytest.mark.parametrize(
    "config",
    [
        {"kind": "tool", "model_vendor": "tool"},
        {"kind": "hitl", "model_vendor": "hitl"},
        {"kind": ActionKind.TOOL, "model_vendor": "openai"},
        {"kind": ActionKind.HITL},
        {"model_vendor": "tool"},
        {"model_vendor": "HITL"},
    ],
)
def test_a_tool_or_hitl_action_under_batch_stays_online(config):
    assert runs_in_batch({**config, "run_mode": RunMode.BATCH}) is False


@pytest.mark.parametrize("run_mode", [RunMode.ONLINE, "online", None])
def test_an_llm_action_not_under_batch_stays_online(run_mode):
    assert runs_in_batch({"kind": "llm", "model_vendor": "openai", "run_mode": run_mode}) is False


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"kind": "llm", "model_vendor": "openai", "run_mode": "batch"}, RunMode.BATCH),
        ({"kind": "tool", "model_vendor": "tool", "run_mode": "batch"}, RunMode.ONLINE),
        ({"kind": "hitl", "model_vendor": "hitl", "run_mode": RunMode.BATCH}, RunMode.ONLINE),
        ({"kind": "llm", "model_vendor": "openai"}, RunMode.ONLINE),
    ],
)
def test_the_effective_run_mode_is_the_path_the_action_takes(config, expected):
    assert effective_run_mode(config) == expected
