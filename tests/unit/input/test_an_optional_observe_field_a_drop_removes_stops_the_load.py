"""An optional observe entry that a drop of the same reference removes stops the load.

The drop runs first, so the field is never there and every record gets the default
without a word. The error names both entries.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig
from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import (
    normalize_context_scope,
    split_optional_observe,
)
from agent_actions.output.response.expander_merge import deep_merge_context_scope

BOTH_NAMED = r"observe entry 'review\.x\?'.*drop entry 'review\.x'"


@pytest.mark.parametrize(
    "entry",
    ["review.x?", {"field": "review.x", "optional": True}, {"field": "review.x", "default": ""}],
    ids=["suffix", "mapping", "default"],
)
def test_the_same_scope_holding_both_is_refused_naming_both(entry):
    with pytest.raises(ConfigurationError, match=BOTH_NAMED):
        split_optional_observe({"observe": ["spec.text", entry], "drop": ["review.x"]})


def test_an_action_holding_both_fails_validation():
    with pytest.raises(ValidationError, match=BOTH_NAMED):
        ActionConfig.model_validate(
            {
                "name": "a",
                "intent": "i",
                "context_scope": {"observe": ["review.x?"], "drop": ["review.x"]},
            }
        )


def test_a_drop_in_the_defaults_and_the_optional_entry_in_the_action_are_refused_once_merged():
    merged = deep_merge_context_scope({"drop": ["review.x"]}, {"observe": ["review.x?"]})

    with pytest.raises(ConfigurationError, match=BOTH_NAMED):
        normalize_context_scope(merged, {})


def test_a_drop_of_another_field_of_the_namespace_is_accepted():
    scope = {"observe": ["review.*", "review.x?"], "drop": ["review.secret"]}

    assert split_optional_observe(scope)["optional"] == {"review.x": None}


def test_the_same_pair_without_the_mark_is_left_to_the_record():
    scope = {"observe": ["review.x"], "drop": ["review.x"]}

    assert split_optional_observe(scope) is scope


def test_a_wildcard_drop_of_the_namespace_is_refused_naming_the_wildcard():
    with pytest.raises(
        ConfigurationError, match=r"observe entry 'review\.x\?'.*drop entry 'review\.\*'"
    ):
        split_optional_observe({"observe": ["review.x?"], "drop": ["review.*"]})


def test_a_wildcard_drop_of_another_namespace_is_accepted():
    scope = {"observe": ["review.x?"], "drop": ["other.*"]}

    assert split_optional_observe(scope)["optional"] == {"review.x": None}


def test_a_drop_of_a_parent_of_a_nested_optional_field_is_refused_naming_the_parent():
    with pytest.raises(
        ConfigurationError,
        match=r"observe entry 'review\.meta\.reason\?'.*drop entry 'review\.meta'",
    ):
        split_optional_observe({"observe": ["review.meta.reason?"], "drop": ["review.meta"]})


def test_a_drop_of_a_sibling_whose_name_starts_the_same_is_accepted():
    scope = {"observe": ["review.meta.reason?"], "drop": ["review.meta_x"]}

    assert split_optional_observe(scope)["optional"] == {"review.meta.reason": None}
