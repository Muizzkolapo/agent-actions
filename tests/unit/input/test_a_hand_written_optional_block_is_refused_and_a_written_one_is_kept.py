"""The workflow file cannot hold a `context_scope.optional` block; the normaliser can.

An author marks an observe entry optional (`a.b?`). The normaliser keeps each such
reference under `optional`, and the load normalises a scope more than once (the
validated action is dumped, merged over the defaults and normalised again), so the
block it wrote itself is read again without a word.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig, dump_defaults
from agent_actions.input.context.normalizer import (
    normalize_all_agent_configs,
    normalize_context_scope,
)
from agent_actions.output.response.expander import ActionExpander
from agent_actions.output.response.expander_merge import deep_merge_context_scope

HAND_WRITTEN = {"observe": ["review.x"], "optional": {"review.x": "z"}}
REFUSAL = "context_scope.optional is not written by hand"


def _action(scope: dict) -> ActionConfig:
    return ActionConfig.model_validate({"name": "a", "intent": "i", "context_scope": scope})


class TestTheWorkflowFileCannotHoldTheBlock:
    def test_an_action_with_a_hand_written_optional_mapping_is_refused(self):
        with pytest.raises(ValidationError, match=REFUSAL):
            _action(HAND_WRITTEN)

    def test_defaults_with_a_hand_written_optional_mapping_are_refused(self):
        with pytest.raises(ValidationError, match=REFUSAL):
            DefaultsConfig.model_validate({"context_scope": HAND_WRITTEN})

    def test_a_hand_written_block_beside_a_marked_entry_is_refused_too(self):
        with pytest.raises(ValidationError, match=REFUSAL):
            _action({"observe": ["review.x?"], "optional": {"review.y": None}})


class TestTheBlockTheNormaliserWroteIsReadAgain:
    def test_a_scope_normalised_twice_is_unchanged(self):
        once = normalize_context_scope({"observe": ["review.x?", "spec.text"]}, {})

        assert once == {"observe": ["review.x", "spec.text"], "optional": {"review.x": None}}
        assert normalize_context_scope(once, {}) == once

    def test_validated_defaults_merged_over_a_validated_action_keep_the_field_optional(self):
        defaults = dump_defaults(
            DefaultsConfig.model_validate({"context_scope": {"observe": ["review.x?"]}})
        )
        action = _action({"observe": [{"field": "spec.text", "default": ""}]}).model_dump(
            exclude_unset=True
        )

        merged = deep_merge_context_scope(defaults["context_scope"], action["context_scope"])

        assert merged == {
            "observe": ["review.x", "spec.text"],
            "optional": {"review.x": None, "spec.text": ""},
        }

    def test_the_expander_and_the_run_normaliser_read_the_dumped_action(self):
        action = _action({"observe": ["review.x?"]}).model_dump(exclude_unset=True)
        defaults = dump_defaults(
            DefaultsConfig.model_validate(
                {
                    "model_vendor": "openai",
                    "model_name": "m",
                    "api_key": "KEY",
                    "context_scope": {"observe": ["spec.text?"]},
                }
            )
        )

        agents = ActionExpander.expand_actions_to_agents(
            {"name": "wf", "actions": [action], "defaults": defaults}
        )
        configs = {agent["agent_type"]: agent for agent in agents["wf"]}
        normalize_all_agent_configs(configs)

        assert configs["a"]["context_scope"] == {
            "observe": ["spec.text", "review.x"],
            "optional": {"spec.text": None, "review.x": None},
        }
