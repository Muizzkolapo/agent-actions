"""A built-in check's parameter of the wrong type is refused where the rule is built.

A string where a list is meant was iterated one character at a time, so
``terms: source.essay`` passed almost any text. Every route that builds a rule
goes through ``Expectation``, so preflight and runtime refuse it in the same words.
"""

import pytest
from pydantic import ValidationError

from agent_actions.expectations import registry
from agent_actions.expectations.loader import build_inline_suite, build_suite_from_schema_data
from agent_actions.expectations.types import Expectation

LITERAL_NOTE = "; params hold literal values, so a field name here is not read"


def _refusal(**rule) -> str:
    with pytest.raises(ValidationError) as caught:
        Expectation(**rule)
    return str(caught.value)


def test_a_string_terms_is_refused():
    text = _refusal(type="contains_terms_from", field="x", params={"terms": "source.essay"})

    assert (
        "type 'contains_terms_from' takes parameter 'terms' as a list, got str "
        "'source.essay'; params hold literal values, so a field name here is not read"
    ) in text


@pytest.mark.parametrize(
    ("rule", "param", "value"),
    [
        pytest.param(
            {"type": "no_forbidden_phrases", "field": "x", "params": {"phrases": "fraud"}},
            "phrases",
            "fraud",
            id="no_forbidden_phrases.phrases",
        ),
        pytest.param(
            {"type": "accepted_values", "field": "x", "params": {"values": "high"}},
            "values",
            "high",
            id="accepted_values.values",
        ),
        pytest.param(
            {"type": "no_null_fields", "params": {"exclude": "abc"}},
            "exclude",
            "abc",
            id="no_null_fields.exclude",
        ),
    ],
)
def test_a_string_phrases_values_exclude_is_refused(rule, param, value):
    text = _refusal(**rule)

    assert (
        f"type '{rule['type']}' takes parameter '{param}' as a list, got str "
        f"{value!r}{LITERAL_NOTE}"
    ) in text


@pytest.mark.parametrize(
    ("type_name", "param", "params"),
    [
        pytest.param("item_count", "equals", {"equals": "1"}, id="item_count.equals"),
        pytest.param("word_count_between", "min", {"min": "1"}, id="word_count_between.min"),
        pytest.param(
            "contains_terms_from",
            "min_matches",
            {"terms": ["a"], "min_matches": "2"},
            id="contains_terms_from.min_matches",
        ),
        pytest.param(
            "word_count_ratio", "max_ratio", {"max_ratio": "2"}, id="word_count_ratio.max_ratio"
        ),
    ],
)
def test_a_string_number_is_refused(type_name, param, params):
    text = _refusal(type=type_name, field="x", params=params)

    assert (
        f"type '{type_name}' takes parameter '{param}' as a number, got str {params[param]!r}"
    ) in text
    assert LITERAL_NOTE not in text


def test_a_bool_is_not_a_number():
    text = _refusal(type="item_count", field="x", params={"min": True})

    assert "type 'item_count' takes parameter 'min' as a number, got bool True" in text


def test_a_number_is_not_a_list():
    text = _refusal(type="accepted_values", field="x", params={"values": 3})

    assert "type 'accepted_values' takes parameter 'values' as a list, got int 3" in text
    assert LITERAL_NOTE not in text


@pytest.mark.parametrize(
    ("type_name", "param", "params", "wanted"),
    [
        pytest.param(
            "matches_regex", "pattern", {"pattern": 5}, "a string", id="matches_regex.pattern"
        ),
        pytest.param(
            "matches_regex",
            "negate",
            {"pattern": "x", "negate": "yes"},
            "a boolean",
            id="matches_regex.negate",
        ),
        pytest.param(
            "no_forbidden_phrases",
            "case_sensitive",
            {"phrases": ["x"], "case_sensitive": 1},
            "a boolean",
            id="no_forbidden_phrases.case_sensitive",
        ),
    ],
)
def test_a_string_or_boolean_param_of_another_type_is_refused(type_name, param, params, wanted):
    text = _refusal(type=type_name, field="x", params=params)

    assert (
        f"type '{type_name}' takes parameter '{param}' as {wanted}, got "
        f"{type(params[param]).__name__} {params[param]!r}"
    ) in text


@pytest.mark.parametrize(
    ("rule", "value", "expected"),
    [
        pytest.param(
            {"type": "no_null_fields", "params": {"exclude": ["note"]}},
            {"answer": "a", "note": None},
            (True, ""),
            id="no_null_fields",
        ),
        pytest.param(
            {"type": "item_count", "field": "x", "params": {"equals": 2, "min": 1, "max": 3}},
            [1, 2],
            (True, ""),
            id="item_count",
        ),
        pytest.param(
            {"type": "word_count_between", "field": "x", "params": {"min": 1, "max": 3}},
            "two words",
            (True, ""),
            id="word_count_between",
        ),
        pytest.param(
            {"type": "word_count_ratio", "field": "x", "params": {"max_ratio": 2.5}},
            ["one two", "three"],
            (True, ""),
            id="word_count_ratio",
        ),
        pytest.param(
            {"type": "accepted_values", "field": "x", "params": {"values": ["high", "low"]}},
            "hi",
            (False, "value 'hi' is not one of ['high', 'low']"),
            id="accepted_values",
        ),
        pytest.param(
            {"type": "matches_regex", "field": "x", "params": {"pattern": "^a", "negate": False}},
            "abc",
            (True, ""),
            id="matches_regex",
        ),
        pytest.param(
            {
                "type": "match_like_pattern",
                "field": "x",
                "params": {"like_pattern": "a%", "negate": True},
            },
            "abc",
            (False, "value 'abc' matched forbidden pattern 'a%'"),
            id="match_like_pattern",
        ),
        pytest.param(
            {
                "type": "no_forbidden_phrases",
                "field": "x",
                "params": {"phrases": ["fraud"], "case_sensitive": False},
            },
            "a perfectly fine note",
            (True, ""),
            id="no_forbidden_phrases",
        ),
        pytest.param(
            {
                "type": "contains_terms_from",
                "field": "x",
                "params": {"terms": ["essay", "thesis"], "min_matches": 1},
            },
            "xyz",
            (False, "matched 0 term(s), expected at least 1 from ['essay', 'thesis']"),
            id="contains_terms_from",
        ),
    ],
)
def test_well_typed_params_are_accepted(rule, value, expected):
    expectation = Expectation(**rule)

    assert registry.get(expectation.type).check(value, expectation.params) == expected


def test_an_absent_optional_param_given_as_null_is_accepted():
    expectation = Expectation(type="item_count", field="x", params={"equals": None, "min": 1})

    assert expectation.params == {"equals": None, "min": 1}


def test_a_user_type_is_not_type_checked():
    name = "user_type_with_no_declared_param_types"
    try:
        registry.expectation_check(name, params=("anything",))(lambda value, params: (True, ""))

        expectation = Expectation(type=name, field="x", params={"anything": "str"})

        assert expectation.params == {"anything": "str"}
    finally:
        registry._REGISTRY.pop(name, None)
        registry._USER_CHECK_SOURCES.pop(name, None)


def test_a_rule_built_at_runtime_is_refused_in_the_same_words():
    rule = {"type": "contains_terms_from", "field": "x", "params": {"terms": "source.essay"}}
    message = (
        "type 'contains_terms_from' takes parameter 'terms' as a list, got str "
        f"'source.essay'{LITERAL_NOTE}"
    )

    with pytest.raises(ValidationError) as inline:
        build_inline_suite([rule], "summarize")
    with pytest.raises(ValidationError) as schema:
        build_suite_from_schema_data("probe_suite", {"expectations": [rule]})

    assert message in str(inline.value)
    assert message in str(schema.value)
