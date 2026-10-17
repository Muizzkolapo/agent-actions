"""A record's identity is derived however deep it nests, and still refuses a non-string key.

The check for string field names walked the record by recursion, so a record about 800
levels deep failed here before it was hashed, in every mode. On Python 3.11 the JSON
encoder behind the hash recursed too, so a record about 1000 levels deep could not be
hashed at all.
"""

import datetime
import decimal
import enum
import json
import uuid

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.utils.id_generation import IDGenerator


class _Color(str, enum.Enum):
    RED = "red"


class _Size(enum.IntEnum):
    BIG = 7


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
    def test_a_record_nested_deeper_than_a_recursive_walk_survives(self, build):
        record = {"deep": build(850, "leaf")}

        assert IDGenerator.derive_source_guid(record) == IDGenerator.derive_source_guid(record)

    @pytest.mark.parametrize("build", [_nested_dict, _nested_list], ids=["dicts", "lists"])
    def test_the_check_for_string_field_names_has_no_depth_limit_of_its_own(self, build):
        IDGenerator._require_string_keys({"deep": build(5000, "leaf")})

    def test_the_same_record_always_gets_the_same_identity(self):
        first = IDGenerator.derive_source_guid({"deep": _nested_list(850, 1)})
        second = IDGenerator.derive_source_guid({"deep": _nested_list(850, 1)})
        other = IDGenerator.derive_source_guid({"deep": _nested_list(850, 2)})

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


_PAYLOADS = [
    "leaf",
    'é ü   \U0001f600 \x00\x1f "quoted" back\\slash\n\t',
    0,
    -12345678901234567890123,
    True,
    False,
    None,
    1.0,
    0.1,
    -0.0,
    1e300,
    float("nan"),
    float("inf"),
    float("-inf"),
    [],
    {},
    (1, "two", None),
    {"b": 1, "a": [2, {"Z": 3, "y": (4,)}], "é": {}, "A": []},
    datetime.date(2024, 1, 2),
    decimal.Decimal("1.10"),
    _Color.RED,
    _Size.BIG,
]


class TestADeepRecordHashesAsTheJsonEncoderWould:
    """Past the 3.11 encoder's recursion limit the identity is the bytes json.dumps gives."""

    @pytest.mark.parametrize("depth", [1200, 5000])
    @pytest.mark.parametrize("build", [_nested_dict, _nested_list], ids=["dicts", "lists"])
    def test_a_record_nested_past_the_encoders_limit_gets_its_identity(self, build, depth):
        record = {"deep": build(depth, "leaf")}
        if build is _nested_dict:
            expected = '{"deep": ' + '{"k": ' * depth + '"leaf"' + "}" * depth + "}"
        else:
            expected = '{"deep": ' + "[" * depth + '"leaf"' + "]" * depth + "}"

        assert IDGenerator.derive_source_guid(record) == str(
            uuid.uuid5(uuid.NAMESPACE_OID, expected)
        )

    @pytest.mark.parametrize("payload", _PAYLOADS, ids=repr)
    def test_every_kind_of_value_is_encoded_byte_for_byte(self, payload):
        depth = 1500
        record = {"z": payload, "deep": _nested_list(depth, payload), "a": 1}
        inner = json.dumps(payload, sort_keys=True, default=str)
        expected = '{"a": 1, "deep": ' + "[" * depth + inner + "]" * depth + ', "z": ' + inner + "}"

        assert IDGenerator.generate_content_hash(record) == str(
            uuid.uuid5(uuid.NAMESPACE_OID, expected)
        )

    def test_a_container_met_twice_deep_down_is_encoded_both_times(self):
        shared = {"ok": [1]}
        record = {"deep": _nested_list(1500, [shared, shared])}
        inner = '[{"ok": [1]}, {"ok": [1]}]'
        expected = '{"deep": ' + "[" * 1500 + inner + "]" * 1500 + "}"

        assert IDGenerator.generate_content_hash(record) == str(
            uuid.uuid5(uuid.NAMESPACE_OID, expected)
        )

    def test_a_deep_cycle_is_still_refused(self):
        record: dict = {"k": None}
        node = record
        for _ in range(2000):
            node["k"] = {"k": None}
            node = node["k"]
        node["k"] = record

        with pytest.raises(ValueError, match="Circular reference"):
            IDGenerator.generate_content_hash({"deep": record})
