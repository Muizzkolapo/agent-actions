"""In sandbox mode each LLM action goes to the mock, and every other action stays as it is.

A HITL action is marked to approve with no human. The paths a run writes move apart from
a real run's only while the mode is on.
"""

from __future__ import annotations

import copy
from pathlib import Path

from agent_actions.config import sandbox
from agent_actions.config.schema import ActionKind


def _configs() -> dict[str, dict]:
    return {
        "extract": {"kind": "llm", "model_vendor": "openai", "model_name": "gpt-4o-mini"},
        "untyped": {"model_vendor": "anthropic", "model_name": "claude-sonnet"},
        "as_enum": {"kind": ActionKind.LLM, "model_vendor": "groq", "model_name": "llama"},
        "flatten": {"kind": "tool", "model_vendor": "tool", "impl": "flatten_pages"},
        "review": {"kind": "hitl", "model_vendor": "hitl", "hitl": {"port": 3001}},
        "seeded": {"kind": "seed", "model_vendor": "openai"},
    }


def test_each_llm_action_goes_to_the_mock_and_keeps_its_model():
    configs = _configs()

    mocked = sandbox.point_at_mock(configs)

    assert mocked == ["extract", "untyped", "as_enum"]
    assert {configs[name]["model_vendor"] for name in mocked} == {"agac-provider"}
    assert [configs[name]["model_name"] for name in mocked] == [
        "gpt-4o-mini",
        "claude-sonnet",
        "llama",
    ]


def test_tool_and_other_actions_are_unchanged():
    configs = _configs()
    before = copy.deepcopy(configs)

    sandbox.point_at_mock(configs)

    for name in ("flatten", "seeded"):
        assert configs[name] == before[name]


def test_a_review_is_approved_with_no_human():
    configs = _configs()

    sandbox.point_at_mock(configs)

    assert configs["review"][sandbox.AUTO_APPROVE_KEY] is True
    assert configs["review"]["model_vendor"] == "hitl"


def test_paths_move_apart_only_inside_the_mode():
    io = Path("agent_io")

    real = (sandbox.status_file(io), sandbox.store_file(io, "wf"), sandbox.run_dir(io))
    with sandbox.sandbox_mode(True):
        moved = (sandbox.status_file(io), sandbox.store_file(io, "wf"), sandbox.run_dir(io))
    after = (sandbox.status_file(io), sandbox.store_file(io, "wf"), sandbox.run_dir(io))

    assert real == after == (io / ".agent_status.json", io / "store" / "wf.db", io)
    assert moved == (
        io / "sandbox" / ".agent_status.json",
        io / "store" / "wf.sandbox.db",
        io / "sandbox",
    )
