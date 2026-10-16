"""A record's identity is derived however deep it nests, and still refuses a non-string key.

The check for string field names walked the record by recursion, so a record about 800
levels deep failed here before it was hashed, in every mode.
"""

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.utils.id_generation import IDGenerator


def _nested_dict(depth: int, innermost) -> dict:
    node = innermost
    for _ in range(depth):
        node = {"k": node}
    return node


def _nested_list(depth: int, innermost) -> list:
    node = innermost
    for _ in range(depth):
        node = [node]
    return node


class TestADeepRecordGetsAnIdentity:
    @pytest.mark.parametrize("build", [_nested_dict, _nested_list], ids=["dicts", "lists"])
    def test_a_record_nested_past_the_recursion_limit(self, build):
        record = {"deep": build(3000, "leaf")}

        assert IDGenerator.derive_source_guid(record) == IDGenerator.derive_source_guid(record)

    def test_the_same_record_always_gets_the_same_identity(self):
        first = IDGenerator.derive_source_guid({"deep": _nested_list(900, 1)})
        second = IDGenerator.derive_source_guid({"deep": _nested_list(900, 1)})
        other = IDGenerator.derive_source_guid({"deep": _nested_list(900, 2)})

        assert first == second
        assert first != other


class TestANonStringKeyIsStillRefused:
    def test_at_the_top(self):
        with pytest.raises(DataValidationError, match="field name 1"):
            IDGenerator.generate_content_hash({1: "x"})

    def test_deep_inside_a_dict(self):
        record = {"deep": _nested_dict(2000, {5: "x"})}

        with pytest.raises(DataValidationError, match="field name 5"):
            IDGenerator.generate_content_hash(record)

    def test_deep_inside_a_list(self):
        record = {"deep": _nested_list(2000, {None: "x"})}

        with pytest.raises(DataValidationError, match="field name None"):
            IDGenerator.generate_content_hash(record)

    def test_the_first_bad_key_reached_depth_first_is_the_one_named(self):
        record = {"a": {1: "inner"}, 2: "outer"}

        with pytest.raises(DataValidationError, match="field name 1"):
            IDGenerator.generate_content_hash(record)

    def test_a_container_met_twice_is_checked_once(self):
        shared = {"ok": 1}

        IDGenerator.generate_content_hash({"a": shared, "b": shared})
