"""``deep_json`` gives what the json module gives, at any nesting depth.

The fallbacks are exercised directly on ordinary values to pin that they produce the same
text and the same values the C codec does; on a deep value they are what runs.
"""

import datetime
import json
import random

import pytest

from agent_actions.utils import deep_json

DEPTH = 100_000
_SCALARS = [
    None,
    True,
    False,
    0,
    -3,
    10**30,
    1.5,
    -0.0,
    1e300,
    float("inf"),
    float("-inf"),
    "",
    'quote " and \\ and \n',
    "café ☃ \U0001f600",
    "\ud800",
    datetime.date(2020, 1, 2),
]


def _random_value(rng: random.Random, depth: int = 0):
    roll = rng.random()
    if depth > 5 or roll < 0.4:
        return rng.choice(_SCALARS)
    if roll < 0.7:
        return [_random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    keys = ["b", "a", "é", "z"]
    return {rng.choice(keys): _random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def _values() -> list:
    rng = random.Random(1479)
    return [_random_value(rng) for _ in range(400)]


def _nested(depth: int) -> list:
    node: list = ["leaf"]
    for _ in range(depth - 1):
        node = [node]
    return node


def _depth(node) -> int:
    depth = 0
    while isinstance(node, list):
        node = node[0]
        depth += 1
    return depth


class TestTheFallbackMatchesTheJsonModule:
    @pytest.mark.parametrize("ensure_ascii", [True, False])
    @pytest.mark.parametrize("sort_keys", [True, False])
    @pytest.mark.parametrize("indent", [None, 0, 2, "\t"])
    def test_the_encoder_writes_the_same_text(self, ensure_ascii, sort_keys, indent):
        for value in _values():
            options = {
                "ensure_ascii": ensure_ascii,
                "sort_keys": sort_keys,
                "default": str,
                "indent": indent,
            }
            assert deep_json._dumps_without_recursion(value, **options) == json.dumps(
                value, **options
            )

    def test_non_string_keys_are_written_as_json_writes_them(self):
        value = {1: "x", 2.5: "y", False: 1, None: 2}

        written = deep_json._dumps_without_recursion(
            value, ensure_ascii=True, sort_keys=False, default=None
        )

        assert written == json.dumps(value)

    def test_a_value_json_cannot_write_is_refused_the_same_way(self):
        with pytest.raises(TypeError, match="not JSON serializable"):
            deep_json._dumps_without_recursion(
                {"a": object()}, ensure_ascii=True, sort_keys=False, default=None
            )

    def test_a_cycle_is_refused(self):
        cycle: list = []
        cycle.append(cycle)

        with pytest.raises(ValueError, match="Circular reference"):
            deep_json._dumps_without_recursion(
                cycle, ensure_ascii=True, sort_keys=False, default=None
            )

    def test_the_decoder_reads_the_same_values(self):
        for value in _values():
            for text in (json.dumps(value, default=str), json.dumps(value, default=str, indent=2)):
                decoded = deep_json._loads_without_recursion(text)
                assert json.dumps(decoded) == json.dumps(json.loads(text))

    def test_a_repeated_key_keeps_the_last_value_in_the_first_position(self):
        text = '{"a": 1, "b": 2, "a": 3}'

        decoded = deep_json._loads_without_recursion(text)

        assert list(decoded.items()) == list(json.loads(text).items())

    @pytest.mark.parametrize(
        "text",
        ["", "[", "[1,]", '{"a" 1}', "[1 2]", "[1] x", "{1: 2}", "nul", '["a]', '{"a": 1,}'],
    )
    def test_text_that_is_not_json_is_refused_as_json_refuses_it(self, text):
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)
        with pytest.raises(json.JSONDecodeError):
            deep_json._loads_without_recursion(text)


class TestADeepValue:
    def test_it_is_written_and_read_back(self):
        value = {"deep": _nested(DEPTH)}

        text = deep_json.dumps(value, ensure_ascii=False)

        assert text == '{"deep": ' + "[" * DEPTH + '"leaf"' + "]" * DEPTH + "}"
        assert _depth(deep_json.loads(text)["deep"]) == DEPTH

    def test_bytes_are_read_as_json_reads_them(self):
        text = "[" * DEPTH + '"café"' + "]" * DEPTH

        assert _depth(deep_json.loads(text.encode("utf-16"))) == DEPTH

    def test_text_that_is_not_json_is_refused_at_any_depth(self):
        with pytest.raises(json.JSONDecodeError):
            deep_json.loads("[" * DEPTH + "]" * (DEPTH - 1))


class TestAnOrdinaryValueTakesTheFastPath:
    def test_the_fallback_is_not_called(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("the fallback ran for an ordinary value")

        monkeypatch.setattr(deep_json, "_dumps_without_recursion", refuse)
        monkeypatch.setattr(deep_json, "_loads_without_recursion", refuse)
        value = {"a": [1, {"b": "c"}]}

        assert deep_json.dumps(value, sort_keys=True) == json.dumps(value, sort_keys=True)
        assert deep_json.loads(json.dumps(value)) == value
