"""Merging a context scope's passthrough keys into a record's content copies it, at any depth.

`update_schema_objects` returns a new content dict, so the record it was given is never
changed. It copied with `copy.deepcopy`, which recurses once per level and fails on a record
about 500 levels deep.
"""

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer

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


class TestUpdateSchemaObjects:
    def test_the_new_content_is_a_full_independent_copy(self):
        new = {"q": "x", "deep": _nested(DEPTH)}

        result = DataTransformer.update_schema_objects({}, new, [])

        assert _depth(result["deep"]) == DEPTH
        _innermost(result["deep"]).append("changed")
        assert _innermost(new["deep"]) == []

    def test_an_old_value_of_the_same_type_replaces_the_new_one_as_a_copy(self):
        old = {"k": {"deep": _nested(DEPTH)}}

        result = DataTransformer.update_schema_objects(old, {"k": {"x": 1}}, ["k"])

        assert _depth(result["k"]["deep"]) == DEPTH
        _innermost(result["k"]["deep"]).append("changed")
        assert _innermost(old["k"]["deep"]) == []

    def test_an_old_value_of_another_type_is_combined_with_the_new_one(self):
        old = {"k": {"deep": _nested(DEPTH)}}

        result = DataTransformer.update_schema_objects(old, {"k": "text"}, ["k"])

        assert result["k"][0] == "text"
        assert _depth(result["k"][1]["deep"]) == DEPTH

    def test_an_old_value_with_no_new_one_is_added_as_a_copy(self):
        old = {"k": {"deep": _nested(DEPTH)}}

        result = DataTransformer.update_schema_objects(old, {}, ["k"])

        assert _depth(result["k"]["deep"]) == DEPTH
        assert result["k"] is not old["k"]
