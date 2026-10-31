"""An inherited `expect:` block adapts to the action it lands on.

A workflow-wide block is a statement about the workflow, not about any one
action. Real workflows mix LLM actions with deterministic tools and
file-granularity writers, and those cannot repair — so a policy that arrived by
inheritance bends, while one the author wrote on the action stands and is
reported.
"""

from __future__ import annotations

import pytest

from agent_actions.output.response.expander import ActionExpander
from agent_actions.output.response.expander_merge import merge_expect

MODEL = {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "k"}
RULE = {"type": "no_null_fields"}
POLICY = {"repair": "auto", "structural": "auto", "max_iterations": 3}

# A tool action is refused without an impl, so every tool fixture carries one.
TOOL = {
    "kind": "tool",
    "impl": "mod.fn",
    "schema": {"name": "t", "fields": [{"name": "out", "type": "string"}]},
}


def expand(defaults_expect, action):
    agents = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "defaults": {**MODEL, "expect": defaults_expect},
            "actions": [{"prompt": "p", **action}],
        }
    )
    return next(a for group in agents.values() for a in group)["expect"]


class TestActionsThatCannotRepair:
    def test_a_tool_action_does_not_inherit_a_bare_repair_policy(self):
        assert expand(POLICY, {"name": "t", **TOOL}) is None

    def test_a_file_granularity_action_does_not_inherit_it_either(self):
        assert expand(POLICY, {"name": "w", "granularity": "file"}) is None

    def test_an_llm_record_action_still_inherits_it(self):
        assert expand(POLICY, {"name": "a"}) == POLICY

    def test_a_tool_action_keeps_inherited_rules_but_stops_repairing(self):
        """Rules are still worth running on a tool's output; regenerating is not."""
        merged = expand({**POLICY, "expectations": [RULE]}, {"name": "t", **TOOL})

        assert merged["repair"] == "none"
        assert merged["expectations"] == [RULE]
        assert "structural" not in merged

    def test_a_tool_action_that_declares_its_own_policy_keeps_it(self):
        """An authored policy is the author's decision; preflight reports it."""
        merged = expand(POLICY, {"name": "t", **TOOL, "expect": {"repair": "auto"}})

        assert merged["repair"] == "auto"


class TestRepairNoneWithInheritedStructural:
    def test_an_action_opting_out_of_repair_drops_the_inherited_structural(self):
        merged = expand(POLICY, {"name": "a", "expect": {"repair": "none"}})

        assert merged["repair"] == "none"
        assert "structural" not in merged

    def test_an_action_that_declares_both_keeps_both(self):
        """Contradictory, but authored — preflight is where that is reported."""
        merged = merge_expect(POLICY, {"repair": "none", "structural": "auto"})

        assert merged == {"repair": "none", "structural": "auto", "max_iterations": 3}

    def test_defaults_repair_none_never_carries_structural_down(self):
        merged = expand({"repair": "none", "structural": "auto"}, {"name": "a"})

        assert "structural" not in merged


class TestUnchangedBehaviour:
    def test_an_action_with_no_inheritance_is_untouched(self):
        merged = expand(None, {"name": "a", "expect": {"repair": "retry"}})

        assert merged == {"repair": "retry"}

    def test_a_tool_action_with_no_expect_anywhere_still_has_none(self):
        assert expand(None, {"name": "t", **TOOL}) is None

    @pytest.mark.parametrize("kind", ["llm", None])
    def test_a_non_tool_record_action_is_unaffected(self, kind):
        action = {"name": "a"} if kind is None else {"name": "a", "kind": kind}
        assert expand(POLICY, action) == POLICY
