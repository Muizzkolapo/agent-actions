"""plain_copy gives a deep, writable copy of a record without recursing once per level."""

import copy

from agent_actions.utils.readonly import plain_copy


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


class TestPlainCopy:
    def test_a_record_far_past_the_recursion_limit_is_copied(self):
        record = {"deep": _nested(5000)}

        copied = plain_copy(record)

        assert _depth(copied["deep"]) == 5000
        assert copied["deep"] is not record["deep"]

    def test_the_copy_is_independent_of_the_original(self):
        record = {"a": [1, {"b": [2, 3]}], "t": (1, 2)}

        copied = plain_copy(record)
        copied["a"][1]["b"].append(4)

        assert record["a"][1]["b"] == [2, 3]

    def test_it_equals_what_deepcopy_produces(self):
        record = {"a": [1, (2, [3, {"z": None}])], "b": {"c": [[], {}]}, "s": {1, 2}}

        assert plain_copy(record) == copy.deepcopy(record)

    def test_shared_structure_stays_shared(self):
        shared = [1]

        copied = plain_copy({"x": shared, "y": shared})

        assert copied["x"] is copied["y"]
        assert copied["x"] is not shared

    def test_a_reference_back_to_a_container_is_kept(self):
        loop: list = []
        loop.append(loop)

        copied = plain_copy(loop)

        assert copied[0] is copied
        assert copied is not loop

    def test_the_copy_is_writable_where_a_view_is_not(self):
        from agent_actions.utils.readonly import readonly_view

        copied = plain_copy(readonly_view({"a": [1]}))

        copied["a"].append(2)
        copied["b"] = 3

        assert copied == {"a": [1, 2], "b": 3}
        assert type(copied) is dict

    def test_scalars_and_none_come_back_unchanged(self):
        for value in (None, 1, 1.5, "s", True):
            assert plain_copy(value) == value
