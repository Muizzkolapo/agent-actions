"""Which actions a run hands a whole file at once, pinned against the pipeline's own rule."""

import pytest

from agent_actions.processing.helpers import replaces_its_file_whole

CASES = [
    ({"kind": "tool", "granularity": "File"}, True),
    ({"kind": "tool", "granularity": "file"}, True),
    ({"model_vendor": "tool", "granularity": "File"}, True),
    ({"kind": "tool", "granularity": "Record"}, False),
    ({"kind": "tool"}, False),
    ({"kind": "hitl", "granularity": "File"}, False),
    ({"kind": "llm", "granularity": "File"}, False),
    ({"granularity": "File"}, False),
    ({}, False),
]


@pytest.mark.parametrize(("config", "expected"), CASES)
def test_the_predicate_agrees_with_the_pipeline(config, expected):
    """`ProcessingPipeline` hands a file whole when its granularity is file and it is a
    tool action, read the same way here so the two cannot drift apart."""
    kind = str(config.get("kind") or "").lower()
    vendor = str(config.get("model_vendor") or "").lower()
    granularity = str(config.get("granularity") or "").lower()
    pipeline_says = granularity == "file" and (kind == "tool" or vendor == "tool")

    assert replaces_its_file_whole(config) is expected
    assert pipeline_says is expected
