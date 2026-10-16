"""A FILE tool that returns nothing leaves a snapshot of each record it was given.

Whether the action skips the empty result or fails its records, each result keeps a
copy of the input record. `copy.deepcopy` recurses once per level and fails on a record
about 500 levels deep, which failed the file before any result was built.
"""

from unittest.mock import patch

import pytest

from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext

DEPTH = 800


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _depth(node: list) -> int:
    depth = 0
    while node:
        node = node[0]
        depth += 1
    return depth


def _invoke_empty(on_empty: str, record: dict):
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file", "on_empty": on_empty},
        agent_name="agg",
    )
    context.source_data = [record]
    with patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=([], True),
    ):
        return FileToolStrategy().invoke([record], context)


@pytest.mark.parametrize("on_empty", ["skip", "warn"])
def test_each_result_keeps_a_full_independent_copy_of_its_record(on_empty):
    record = {"source_guid": "sg-1", "content": {"src": {"deep": _nested(DEPTH)}}}

    results = _invoke_empty(on_empty, record)

    assert len(results) == 1
    snapshot = results[0].source_snapshot
    assert _depth(snapshot["content"]["src"]["deep"]) == DEPTH
    assert snapshot["content"]["src"]["deep"] is not record["content"]["src"]["deep"]
