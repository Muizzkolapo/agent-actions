"""Rules on an action whose strategy never runs them must not be listed as live."""

from types import SimpleNamespace

import pytest

from agent_actions.processing.helpers import bypasses_expectations
from agent_actions.workflow.pipeline import ProcessingPipeline

CASES = [
    ({"kind": "tool", "granularity": "File"}, True),
    ({"kind": "tool", "granularity": "Record"}, False),
    ({"kind": "hitl", "granularity": "File"}, True),
    ({"kind": "llm", "granularity": "File"}, False),
    ({"kind": "llm", "granularity": "Record"}, False),
    ({"model_vendor": "tool", "granularity": "file"}, True),
    ({"model_vendor": "hitl", "granularity": "file"}, True),
    ({}, False),
]


@pytest.mark.parametrize(("config", "expected"), CASES)
def test_the_predicate_agrees_with_the_strategy_the_pipeline_would_pick(config, expected):
    """Pinned against `_select_strategy` itself, so the two cannot drift apart."""
    online = object()
    kind = str(config.get("kind") or "").lower()
    vendor = str(config.get("model_vendor") or "").lower()
    pipeline = SimpleNamespace(
        granularity=str(config.get("granularity") or "").lower(),
        is_tool_action=kind == "tool" or vendor == "tool",
        is_hitl_action=kind == "hitl" or vendor == "hitl",
        _online_strategy=online,
    )
    routed_away = ProcessingPipeline._select_strategy(pipeline) is not online

    assert bypasses_expectations(config) == expected
    assert routed_away == expected, "the predicate disagrees with the pipeline's own routing"
