"""An action's output nested hundreds of levels deep is wrapped into its record.

`RecordEnvelope.build` copies the output so the caller may change it afterwards.
`copy.deepcopy` recurses once per level and fails on an output about 500 levels deep.
"""

from agent_actions.record.envelope import RecordEnvelope

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


def _innermost(node: list) -> list:
    while node:
        node = node[0]
    return node


def test_the_output_is_wrapped_as_a_full_independent_copy():
    output = {"answer": "x", "deep": _nested(DEPTH)}

    record = RecordEnvelope.build("act", output, None)

    wrapped = record["content"]["act"]["deep"]
    assert _depth(wrapped) == DEPTH
    _innermost(output["deep"]).append("changed")
    assert _innermost(wrapped) == []
