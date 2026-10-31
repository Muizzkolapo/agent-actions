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


@pytest.mark.parametrize(
    ("selector", "match"),
    [
        pytest.param("missing", "missing", id="missing-field"),
        pytest.param(["options", "nope"], "nope", id="missing-field-inside-list-selector"),
        pytest.param("count[*]", "int", id="wildcard-on-non-list-names-the-type"),
        pytest.param("missing[*]", "missing", id="wildcard-on-missing-field"),
    ],
)
def test_unresolvable_selector_raises_naming_the_problem(selector, match):
    with pytest.raises(FieldResolutionError, match=match):
        resolve(RECORD, selector)


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

    @pytest.mark.parametrize(
        ("llm_context", "ref"),
        [
            pytest.param({}, "missing_action.field", id="action-missing"),
            pytest.param({"a": {"other_field": 1}}, "a.field", id="field-missing-on-action"),
            pytest.param({"a": {"x": 1}}, "no_dot_here", id="malformed-ref-without-dot"),
        ],
    )
    def test_raises_on_unresolvable_ref(self, llm_context, ref):
        with pytest.raises(FieldResolutionError):
            resolve_context(llm_context, [ref])

    def test_same_field_name_on_different_actions_does_not_collide(self):
        llm_context = {"action_one": {"text": "from one"}, "action_two": {"text": "from two"}}
        result = resolve_context(llm_context, ["action_one.text", "action_two.text"])
        assert result == {"action_one.text": "from one", "action_two.text": "from two"}
