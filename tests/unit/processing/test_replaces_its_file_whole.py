"""Which actions a run hands a whole file at once, pinned against the pipeline's own rule."""

import pytest

from agent_actions.processing.helpers import replaces_its_file_whole
from agent_actions.workflow.pipeline import _whole_file_readers

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


class TestWhichReadersBelowTakeTheWholeFile:
    CONFIGS = {
        "final": {"kind": "tool", "granularity": "Record"},
        "count": {"kind": "tool", "granularity": "File"},
        "review": {"kind": "hitl", "granularity": "File"},
    }

    def test_a_file_tool_below_is_one(self):
        assert _whole_file_readers(["final", "count", "review"], self.CONFIGS) == {"count"}

    def test_an_action_the_graph_holds_but_the_config_does_not_is_taken_for_one(self):
        """Cleared as before rows were put back, never carried on a guess."""
        assert _whole_file_readers(["final", "gone"], self.CONFIGS) == {"gone"}

    def test_with_no_configs_at_all_every_reader_is_one(self):
        assert _whole_file_readers(["final", "count"], None) == {"final", "count"}
