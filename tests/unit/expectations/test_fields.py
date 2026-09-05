"""Field selector semantics: bare name, per-element, and multi-field."""

import pytest

from agent_actions.expectations.fields import (
    FieldResolutionError,
    referenced_names,
    resolve,
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
