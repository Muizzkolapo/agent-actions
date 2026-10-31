"""Merging an `expect:` block from workflow defaults with an action's own.

The policy half of the block (repair, max_iterations, on_exhausted) is a
workflow-wide decision; the rules half is per action. Merging key by key is
what lets both be stated where they belong.
"""

from __future__ import annotations

import pytest

from agent_actions.config.schema import DefaultsConfig
from agent_actions.output.response.expander_merge import merge_expect

RULE = {"type": "no_null_fields"}

# The expander refuses an agent with no model resolved, so every fixture carries one.
MODEL = {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "k"}


def _by_name(agents, action_name):
    """The expanded agent for one action; the mapping is keyed by workflow, not action."""
    return next(a for group in agents.values() for a in group if a["name"] == action_name)


class TestMergeExpect:
    def test_defaults_alone_are_inherited(self):
        assert merge_expect({"repair": "auto", "max_iterations": 5}, None) == {
            "repair": "auto",
            "max_iterations": 5,
        }

    def test_an_action_block_alone_is_untouched(self):
        assert merge_expect(None, {"expectations": [RULE]}) == {"expectations": [RULE]}

    def test_neither_yields_nothing(self):
        assert merge_expect(None, None) is None

    def test_the_action_wins_key_by_key(self):
        result = merge_expect(
            {"repair": "auto", "max_iterations": 3},
            {"repair": "retry"},
        )
        assert result == {"repair": "retry", "max_iterations": 3}

    def test_a_workflow_policy_survives_an_action_that_only_adds_rules(self):
        """The case whole-value replacement gets wrong.

        An author sets `repair: retry` once for the workflow; an action adds
        rules and says nothing about repair. Replacing the block would silently
        return that action to the `auto` default.
        """
        result = merge_expect({"repair": "retry"}, {"expectations": [RULE]})

        assert result == {"repair": "retry", "expectations": [RULE]}

    def test_rules_are_not_concatenated_across_levels(self):
        """An action's rule list replaces, so a rule cannot arrive from two places."""
        result = merge_expect(
            {"expectations": [{"type": "not_null", "field": "a"}]},
            {"expectations": [RULE]},
        )
        assert result["expectations"] == [RULE]

    def test_a_suite_reference_overrides_an_inherited_rule_list(self):
        result = merge_expect({"expectations": [RULE]}, {"suite": "shared"})
        assert result["suite"] == "shared"

    def test_the_merged_block_does_not_alias_either_input(self):
        defaults = {"repair": "auto", "expectations": [RULE]}
        action = {"max_iterations": 2}

        result = merge_expect(defaults, action)
        result["repair"] = "none"
        result["expectations"].append({"type": "not_null", "field": "z"})

        assert defaults["repair"] == "auto"
        assert defaults["expectations"] == [RULE]

    @pytest.mark.parametrize("bad", ["auto", ["a"], 3])
    def test_a_non_mapping_block_is_ignored_rather_than_crashing(self, bad):
        """ExpectConfig rejects these at validation; the merge must not raise first."""
        assert merge_expect(bad, {"repair": "retry"}) == {"repair": "retry"}
        assert merge_expect({"repair": "retry"}, bad) == {"repair": "retry"}


class TestThroughTheExpander:
    """The merge reaching a real agent config, not just the helper in isolation."""

    @staticmethod
    def _expand(defaults, action_expect):
        from agent_actions.output.response.expander import ActionExpander

        action = {"name": "act", "prompt": "p"}
        if action_expect is not None:
            action["expect"] = action_expect
        agents = ActionExpander.expand_actions_to_agents(
            {"name": "wf", "defaults": {**MODEL, **defaults}, "actions": [action]}
        )
        return _by_name(agents, "act")["expect"]

    def test_a_defaults_only_policy_reaches_an_action_that_declares_nothing(self):
        assert self._expand({"expect": {"repair": "retry"}}, None) == {"repair": "retry"}

    def test_an_action_adding_rules_keeps_the_workflow_policy(self):
        merged = self._expand({"expect": {"repair": "retry"}}, {"expectations": [RULE]})

        assert merged == {"repair": "retry", "expectations": [RULE]}

    def test_an_action_overrides_the_policy_it_names(self):
        merged = self._expand(
            {"expect": {"repair": "retry", "max_iterations": 5}}, {"repair": "none"}
        )

        assert merged == {"repair": "none", "max_iterations": 5}

    def test_no_expect_anywhere_leaves_the_action_without_one(self):
        assert self._expand({}, None) is None

    def test_two_actions_do_not_share_the_inherited_block(self):
        from agent_actions.output.response.expander import ActionExpander

        agents = ActionExpander.expand_actions_to_agents(
            {
                "name": "wf",
                "defaults": {**MODEL, "expect": {"repair": "retry", "expectations": [RULE]}},
                "actions": [{"name": "a", "prompt": "p"}, {"name": "b", "prompt": "p"}],
            }
        )
        _by_name(agents, "a")["expect"]["expectations"].append({"type": "not_null", "field": "z"})

        assert _by_name(agents, "b")["expect"]["expectations"] == [RULE]


class TestDefaultsConfigSlot:
    def test_expect_survives_workflow_defaults(self):
        defaults = DefaultsConfig(expect={"repair": "auto", "max_iterations": 2})
        dumped = defaults.model_dump(exclude_unset=True)

        assert "expect" in dumped
        assert dumped["expect"]["repair"] == "auto"

    def test_an_invalid_expect_block_is_refused_at_the_defaults_level(self):
        with pytest.raises(ValueError, match="repair"):
            DefaultsConfig(expect={"repair": "sideways"})

    def test_defaults_still_accept_no_expect(self):
        assert DefaultsConfig().expect is None
