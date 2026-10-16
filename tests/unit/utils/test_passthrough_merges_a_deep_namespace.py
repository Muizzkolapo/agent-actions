"""Merging passthrough namespaces copies them, whatever their depth.

The merge copies what it adds so the record's content never shares a namespace with the
passthrough fields it came from. `copy.deepcopy` recurses once per level and fails on a
namespace about 500 levels deep.
"""

from agent_actions.utils.transformation.passthrough import merge_passthrough_namespaces

DEPTH = 800


def _nested(depth: int) -> list:
    node: list = []
    for _ in range(depth):
        node = [node]
    return node


def _innermost(node: list) -> list:
    while node:
        node = node[0]
    return node


def _depth(node: list) -> int:
    depth = 0
    while node:
        node = node[0]
        depth += 1
    return depth


class TestAPassthroughNamespaceNestedDeeply:
    def test_a_namespace_the_content_lacks_is_copied_whole(self):
        content: dict = {"act": {"v": 1}}
        fields = {"ctx": {"deep": _nested(DEPTH)}}

        merge_passthrough_namespaces(content, fields, "act")

        assert _depth(content["ctx"]["deep"]) == DEPTH
        _innermost(content["ctx"]["deep"]).append("changed")
        assert _innermost(fields["ctx"]["deep"]) == []

    def test_fields_the_content_lacks_are_added_to_a_namespace_it_has(self):
        content: dict = {"act": {"v": 1}, "ctx": {"a": 1}}
        fields = {"ctx": {"a": 1, "deep": _nested(DEPTH)}}

        merge_passthrough_namespaces(content, fields, "act")

        assert content["ctx"]["a"] == 1
        assert _depth(content["ctx"]["deep"]) == DEPTH
        _innermost(content["ctx"]["deep"]).append("changed")
        assert _innermost(fields["ctx"]["deep"]) == []
