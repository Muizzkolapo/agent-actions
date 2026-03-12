"""Tests for ActionExpander template variable replacement (${param} and ${param-1})."""

import pytest

from agent_actions.output.response.expander import ActionExpander


class TestTemplateVariableReplacement:
    """Test suite for template variable replacement in loops."""

    def test_current_iteration_template_var(self):
        """Test that ${param} is replaced with current iteration."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "process",
                    "intent": "Process with template vars",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Processing stage ${stage}",
                    "versions": {"param": "stage", "range": [1, 3]},
                }
            ],
            "plan": ["process"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert len(agents) == 3
        assert agents[0]["prompt"] == "Processing stage 1"
        assert agents[1]["prompt"] == "Processing stage 2"
        assert agents[2]["prompt"] == "Processing stage 3"

    def test_previous_iteration_template_var(self):
        """Test that ${param-1} is replaced with previous iteration."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "refine",
                    "intent": "Refine with previous reference",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Refine output from stage ${stage-1}",
                    "versions": {"param": "stage", "range": [1, 4], "mode": "sequential"},
                }
            ],
            "plan": ["refine"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert len(agents) == 4
        assert agents[0]["prompt"] == "Refine output from stage "
        assert agents[1]["prompt"] == "Refine output from stage 1"
        assert agents[2]["prompt"] == "Refine output from stage 2"
        assert agents[3]["prompt"] == "Refine output from stage 3"

    def test_both_template_vars_in_same_string(self):
        """Test using both ${param} and ${param-1} in the same string."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "compare",
                    "intent": "Compare iterations",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Compare stage ${i} with stage ${i-1}",
                    "versions": {"param": "i", "range": [1, 3]},
                }
            ],
            "plan": ["compare"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert agents[0]["prompt"] == "Compare stage 1 with stage "
        assert agents[1]["prompt"] == "Compare stage 2 with stage 1"
        assert agents[2]["prompt"] == "Compare stage 3 with stage 2"

    def test_template_vars_in_nested_dict(self):
        """Test template variables in nested dictionary structures."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "structured",
                    "intent": "Structured with nested template vars",
                    "api_key": "OPENAI_API_KEY",
                    "schema": {
                        "current": "stage_${n}",
                        "previous": "stage_${n-1}",
                        "nested": {"value": "iteration_${n}"},
                    },
                    "versions": {"param": "n", "range": [5, 6]},
                }
            ],
            "plan": ["structured"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        schema1 = agents[0]["schema"]
        assert schema1["current"] == "stage_5"
        assert schema1["previous"] == "stage_"
        assert schema1["nested"]["value"] == "iteration_5"
        schema2 = agents[1]["schema"]
        assert schema2["current"] == "stage_6"
        assert schema2["previous"] == "stage_5"
        assert schema2["nested"]["value"] == "iteration_6"

    def test_template_vars_with_non_numeric_range(self):
        """Test template variables with explicit list range."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "process",
                    "intent": "Process with list range",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Stage ${idx} (prev: ${idx-1})",
                    "versions": {"param": "idx", "range": [10, 20, 30]},
                }
            ],
            "plan": ["process"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert len(agents) == 3
        assert agents[0]["prompt"] == "Stage 10 (prev: )"
        assert agents[1]["prompt"] == "Stage 20 (prev: 10)"
        assert agents[2]["prompt"] == "Stage 30 (prev: 20)"

    def test_template_var_without_previous_ref(self):
        """Test that ${param} works without ${param-1}."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "simple",
                    "intent": "Simple template var",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Iteration ${iter} only",
                    "versions": {"param": "iter", "range": [1, 2]},
                }
            ],
            "plan": ["simple"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert agents[0]["prompt"] == "Iteration 1 only"
        assert agents[1]["prompt"] == "Iteration 2 only"

    def test_multiple_previous_refs_in_string(self):
        """Test multiple ${param-1} occurrences in the same string."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "multi",
                    "intent": "Multiple previous refs",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Compare ${x-1} with ${x-1} again",
                    "versions": {"param": "x", "range": [1, 2]},
                }
            ],
            "plan": ["multi"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]
        assert agents[0]["prompt"] == "Compare  with  again"
        assert agents[1]["prompt"] == "Compare 1 with 1 again"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
