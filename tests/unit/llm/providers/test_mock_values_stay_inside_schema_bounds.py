"""The mock keeps a generated value inside the bound its schema declares.

A declared `minimum`/`maximum` wins over the mock's field-name rules (a `score` was drawn
from 1..100 whatever its schema said), and the value is drawn across the bound rather than
clamped onto its edge. A field with no bound keeps its name rule. String length bounds hold
too. Both schema shapes the mock receives are covered: JSON Schema properties and the
unified `fields:` list.
"""

from __future__ import annotations

from collections import Counter

import pytest

from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.output.response.vendor_compilation import compile_unified_schema

NAMES = ["score", "rating", "age", "count", "price", "confidence", "value"]


def _values(schema: dict, field: str) -> list:
    values = []
    for seed in range(50):
        for attempt in (1, 2, 3):
            FakeDataGenerator.set_context(seed=seed)
            values.append(FakeDataGenerator.generate_from_schema(schema, attempt, field_name=field))
    return values


@pytest.mark.parametrize("name", NAMES)
def test_an_integer_stays_inside_its_bound(name):
    values = _values({"type": "integer", "minimum": 1, "maximum": 4}, name)

    assert all(isinstance(v, int) and 1 <= v <= 4 for v in values), sorted(set(values))


@pytest.mark.parametrize("name", NAMES)
def test_a_number_stays_inside_its_bound(name):
    values = _values({"type": "number", "minimum": 0, "maximum": 1}, name)

    assert all(0 <= v <= 1 for v in values), sorted(set(values))


def test_a_bounded_integer_is_spread_across_the_bound_not_piled_on_an_edge():
    counts = Counter(_values({"type": "integer", "minimum": 1, "maximum": 4}, "score"))

    assert set(counts) == {1, 2, 3, 4}
    assert max(counts.values()) < 0.5 * sum(counts.values())


@pytest.mark.parametrize("field_type", ["integer", "number"])
def test_a_one_point_bound_returns_that_point(field_type):
    values = _values({"type": field_type, "minimum": 3, "maximum": 3}, "score")

    assert set(values) == {3}


def test_an_unbounded_field_keeps_its_name_rule():
    values = _values({"type": "integer"}, "age")

    assert all(18 <= v <= 80 for v in values)
    assert max(values) > 4


def test_the_unified_fields_form_stays_inside_its_bound():
    schema = {"fields": [{"id": "score", "type": "integer", "minimum": 1, "maximum": 4}]}

    for seed in range(50):
        FakeDataGenerator.set_context(seed=seed)
        assert 1 <= FakeDataGenerator.generate_from_schema(schema)["score"] <= 4


@pytest.mark.parametrize("name", ["summary", "email", "title"])
def test_a_string_length_stays_inside_its_bound(name):
    values = _values({"type": "string", "minLength": 5, "maxLength": 8}, name)

    assert all(5 <= len(v) <= 8 for v in values), sorted({len(v) for v in values})


def test_a_long_minimum_length_is_met():
    values = _values({"type": "string", "minLength": 300}, "summary")

    assert all(len(v) >= 300 for v in values)


def test_a_bounded_number_keeps_its_multiple():
    values = _values({"type": "number", "minimum": 0, "maximum": 10, "multipleOf": 0.5}, "score")

    assert all(0 <= v <= 10 and (v * 2).is_integer() for v in values), sorted(set(values))
    assert len(set(values)) > 2


def test_a_maximum_length_alone_never_empties_a_string():
    values = _values({"type": "string", "maxLength": 20}, "summary")

    assert all(1 <= len(v) <= 20 for v in values), sorted({len(v) for v in values})
    assert not any(v.endswith(" ") for v in values)


def test_a_long_string_is_cut_at_a_word_boundary():
    whole = _values({"type": "string"}, "summary")
    cut = _values({"type": "string", "maxLength": 20}, "summary")

    for full, short in zip(whole, cut, strict=True):
        assert full.startswith(short), (full, short)
        assert len(full) == len(short) or full[len(short)] == " ", (full, short)
    assert any(len(full) > 20 for full in whole)


def test_a_formatted_string_keeps_its_format_over_a_length_bound():
    values = _values({"type": "string", "format": "email", "minLength": 60}, "email")

    assert all(v.count("@") == 1 and " " not in v for v in values), values[:3]


@pytest.mark.parametrize(
    ("schema", "name", "low", "high"),
    [
        ({"type": "integer", "maximum": 4}, "score", 0, 4),
        ({"type": "number", "maximum": 1}, "confidence", 0, 1),
        ({"type": "integer", "minimum": -3}, "count", -3, 997),
    ],
    ids=["integer_max_only", "number_max_only", "integer_min_only"],
)
def test_a_one_sided_bound_is_completed_near_it(schema, name, low, high):
    values = _values(schema, name)

    assert all(low <= v <= high for v in values), (min(values), max(values))


def test_a_bounded_number_is_spread_across_the_bound():
    values = _values({"type": "number", "minimum": 0, "maximum": 1}, "score")

    assert len(set(values)) > 10
    assert min(values) < 0.25 and max(values) > 0.75


def test_exclusive_bounds_are_kept_strictly():
    numbers = _values({"type": "number", "exclusiveMinimum": 0, "maximum": 1}, "confidence")
    integers = _values({"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 4}, "score")

    assert all(0 < v <= 1 for v in numbers), min(numbers)
    assert set(integers) == {1, 2, 3}


def test_a_value_never_lands_on_an_open_edge():
    narrow = _values({"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 0.01}, "x")
    stepped = _values(
        {"type": "number", "exclusiveMinimum": 0.3, "maximum": 0.5, "multipleOf": 0.1}, "x"
    )

    assert all(0 < v < 0.01 for v in narrow), sorted(set(narrow))
    assert all(0.3 < v <= 0.5 for v in stepped), sorted(set(stepped))
    assert all(abs(v / 0.1 - round(v / 0.1)) < 1e-9 for v in stepped)


@pytest.mark.parametrize("step", [10, 10.0])
def test_a_bounded_integer_keeps_its_multiple(step):
    values = _values({"type": "integer", "minimum": 0, "maximum": 100, "multipleOf": step}, "count")

    assert all(v % 10 == 0 and 0 <= v <= 100 for v in values), sorted(set(values))
    assert len(set(values)) > 3


def test_an_unknown_format_is_held_to_its_length():
    values = _values({"type": "string", "format": "markdown", "maxLength": 20}, "notes")

    assert all(1 <= len(v) <= 20 for v in values), sorted({len(v) for v in values})


def test_an_integer_bound_beyond_float_precision_stays_exact():
    big = 2**53 + 1

    assert set(_values({"type": "integer", "minimum": big, "maximum": big}, "score")) == {big}


@pytest.mark.parametrize(
    "fmt", ["email", "uri", "url", "date", "date-time", "time", "uuid", "hostname", "ipv4", "ipv6"]
)
def test_each_known_format_is_generated_as_that_format(fmt):
    values = _values({"type": "string", "format": fmt}, "value")

    assert all(" " not in v for v in values), values[:3]


def test_bounds_hold_through_the_schema_the_mock_is_sent():
    unified = {
        "name": "scored",
        "fields": [
            {"id": "score", "type": "integer", "minimum": 1, "maximum": 4},
            {"id": "confidence", "type": "number", "minimum": 0, "maximum": 1},
            {"id": "email", "type": "string", "minLength": 30, "maxLength": 40},
        ],
    }
    schema = FakeDataGenerator.unwrap_schema(compile_unified_schema(unified, "agac-provider"))

    for seed in range(30):
        FakeDataGenerator.set_context(seed=seed)
        row = FakeDataGenerator.generate_from_schema(schema)
        assert 1 <= row["score"] <= 4
        assert 0 <= row["confidence"] <= 1
        assert 30 <= len(row["email"]) <= 40
