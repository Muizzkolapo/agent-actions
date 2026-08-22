"""Field selector semantics: bare name, per-element, and multi-field."""

import pytest

from agent_actions.expectations.fields import (
    FieldResolutionError,
    referenced_names,
    resolve,
    resolve_context,
)

RECORD = {"options": ["alpha", "beta"], "answer": "alpha", "count": 2}


def test_bare_name_yields_one_input_holding_the_whole_value():
    assert resolve(RECORD, "options") == [["alpha", "beta"]]


def test_wildcard_yields_one_input_per_element():
    assert resolve(RECORD, "options[*]") == ["alpha", "beta"]


def test_list_selector_yields_a_single_combined_input():
    assert resolve(RECORD, ["options", "answer"]) == [[["alpha", "beta"], "alpha"]]


def test_missing_field_raises_with_the_field_name():
    with pytest.raises(FieldResolutionError, match="missing"):
        resolve(RECORD, "missing")


def test_missing_field_inside_list_selector_raises():
    with pytest.raises(FieldResolutionError, match="nope"):
        resolve(RECORD, ["options", "nope"])


def test_wildcard_on_a_non_list_raises_naming_the_actual_type():
    with pytest.raises(FieldResolutionError, match="int"):
        resolve(RECORD, "count[*]")


def test_wildcard_on_a_missing_field_raises_rather_than_defaulting_to_empty():
    with pytest.raises(FieldResolutionError, match="missing"):
        resolve(RECORD, "missing[*]")


def test_wildcard_on_empty_list_yields_no_inputs():
    assert resolve({"options": []}, "options[*]") == []


def test_referenced_names_strips_the_wildcard_suffix():
    assert referenced_names("options[*]") == ["options"]


def test_referenced_names_returns_every_name_in_a_list_selector():
    assert referenced_names(["options", "answer"]) == ["options", "answer"]


def test_referenced_names_of_a_bare_name_is_that_name():
    assert referenced_names("answer") == ["answer"]


class TestResolveContext:
    def test_resolves_a_single_ref(self):
        llm_context = {"extract_quote_context": {"source_context": "the docs say X"}}
        assert resolve_context(llm_context, ["extract_quote_context.source_context"]) == {
            "extract_quote_context.source_context": "the docs say X"
        }

    def test_resolves_multiple_refs(self):
        llm_context = {"a": {"x": 1}, "b": {"y": 2}}
        result = resolve_context(llm_context, ["a.x", "b.y"])
        assert result == {"a.x": 1, "b.y": 2}

    def test_raises_when_action_missing(self):
        with pytest.raises(FieldResolutionError):
            resolve_context({}, ["missing_action.field"])

    def test_raises_when_field_missing_on_present_action(self):
        with pytest.raises(FieldResolutionError):
            resolve_context({"a": {"other_field": 1}}, ["a.field"])

    def test_raises_on_malformed_ref_without_a_dot(self):
        with pytest.raises(FieldResolutionError):
            resolve_context({"a": {"x": 1}}, ["no_dot_here"])

    def test_same_field_name_on_different_actions_does_not_collide(self):
        llm_context = {"action_one": {"text": "from one"}, "action_two": {"text": "from two"}}
        result = resolve_context(llm_context, ["action_one.text", "action_two.text"])
        assert result == {"action_one.text": "from one", "action_two.text": "from two"}
