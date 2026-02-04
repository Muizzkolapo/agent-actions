"""Tests for version context injection in versioned actions.

This tests the fix for version template variables ({{ i }}, {{ loop.length }}, etc.)
being available in prompt store references.
"""

import pytest
from agent_actions.output.response.expander import ActionExpander


class TestVersionContextCompilation:
    """Test suite for _version_context compilation during expansion."""

    def test_version_context_added_to_agent_config(self):
        """Verify _version_context is added to each versioned agent."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "classify",
                    "intent": "Classify with version context",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Classify item",
                    "versions": {"range": [1, 3], "mode": "parallel"},
                }
            ],
            "plan": ["classify"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        assert len(agents) == 3

        # All agents should have _version_context
        for agent in agents:
            assert "_version_context" in agent
            assert isinstance(agent["_version_context"], dict)

    def test_version_context_has_i_and_idx(self):
        """Verify _version_context contains i (iteration value) and idx (zero-based index)."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "process",
                    "intent": "Process",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Process",
                    "versions": {"range": [1, 3]},
                }
            ],
            "plan": ["process"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        # Agent 1: i=1, idx=0
        assert agents[0]["_version_context"]["i"] == 1
        assert agents[0]["_version_context"]["idx"] == 0

        # Agent 2: i=2, idx=1
        assert agents[1]["_version_context"]["i"] == 2
        assert agents[1]["_version_context"]["idx"] == 1

        # Agent 3: i=3, idx=2
        assert agents[2]["_version_context"]["i"] == 3
        assert agents[2]["_version_context"]["idx"] == 2

    def test_version_context_has_length(self):
        """Verify _version_context contains length (total iterations)."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "extract",
                    "intent": "Extract",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Extract",
                    "versions": {"range": [1, 5]},  # 5 iterations
                }
            ],
            "plan": ["extract"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        # All agents should know total length
        for agent in agents:
            assert agent["_version_context"]["length"] == 5

    def test_version_context_has_first_and_last_flags(self):
        """Verify _version_context contains first and last boolean flags."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "analyze",
                    "intent": "Analyze",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Analyze",
                    "versions": {"range": [1, 3]},
                }
            ],
            "plan": ["analyze"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        # First agent: first=True, last=False
        assert agents[0]["_version_context"]["first"] is True
        assert agents[0]["_version_context"]["last"] is False

        # Middle agent: first=False, last=False
        assert agents[1]["_version_context"]["first"] is False
        assert agents[1]["_version_context"]["last"] is False

        # Last agent: first=False, last=True
        assert agents[2]["_version_context"]["first"] is False
        assert agents[2]["_version_context"]["last"] is True

    def test_version_context_single_iteration(self):
        """Verify first and last are both True for single iteration."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "single",
                    "intent": "Single",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Single",
                    "versions": {"range": [1, 1]},  # Single iteration
                }
            ],
            "plan": ["single"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        assert len(agents) == 1
        assert agents[0]["_version_context"]["first"] is True
        assert agents[0]["_version_context"]["last"] is True
        assert agents[0]["_version_context"]["length"] == 1

    def test_custom_param_name_in_version_context(self):
        """Verify custom param names are included in version context."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "classify",
                    "intent": "Classify",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Classify",
                    "versions": {"param": "classifier_id", "range": [1, 3]},
                }
            ],
            "plan": ["classify"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        # Custom param should be available
        assert agents[0]["_version_context"]["classifier_id"] == 1
        assert agents[1]["_version_context"]["classifier_id"] == 2
        assert agents[2]["_version_context"]["classifier_id"] == 3

        # Standard 'i' should still be available too
        assert agents[0]["_version_context"]["i"] == 1
        assert agents[1]["_version_context"]["i"] == 2
        assert agents[2]["_version_context"]["i"] == 3

    def test_default_param_name_not_duplicated(self):
        """Verify default param 'i' doesn't create duplicate entry."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "process",
                    "intent": "Process",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Process",
                    "versions": {"param": "i", "range": [1, 2]},  # Default param name
                }
            ],
            "plan": ["process"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        # Should only have standard keys, no duplicate 'i'
        version_context = agents[0]["_version_context"]
        expected_keys = {"i", "idx", "length", "first", "last"}
        assert set(version_context.keys()) == expected_keys

    def test_version_context_with_explicit_list_range(self):
        """Verify version context works with explicit list ranges."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "process",
                    "intent": "Process",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Process",
                    "versions": {"range": [10, 20, 30]},  # Explicit list
                }
            ],
            "plan": ["process"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        assert len(agents) == 3

        # i values should be 10, 20, 30
        assert agents[0]["_version_context"]["i"] == 10
        assert agents[1]["_version_context"]["i"] == 20
        assert agents[2]["_version_context"]["i"] == 30

        # idx should be 0, 1, 2
        assert agents[0]["_version_context"]["idx"] == 0
        assert agents[1]["_version_context"]["idx"] == 1
        assert agents[2]["_version_context"]["idx"] == 2

        # length should be 3
        for agent in agents:
            assert agent["_version_context"]["length"] == 3

    def test_non_versioned_action_has_no_version_context(self):
        """Verify non-versioned actions don't have _version_context."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": "simple",
                    "intent": "Simple non-versioned action",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Simple prompt",
                    # No versions config
                }
            ],
            "plan": ["simple"],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        agents = result["test_workflow"]

        assert len(agents) == 1
        assert "_version_context" not in agents[0]
        assert agents[0].get("is_versioned_agent") is not True


class TestVersionContextInFieldContext:
    """Test that version context flows correctly to field_context for Jinja2 rendering."""

    def test_version_namespace_structure(self):
        """Verify the version namespace has the correct structure for Jinja2."""
        from agent_actions.prompt.context.scope import ContextScopeProcessor

        version_context = {
            "i": 2,
            "idx": 1,
            "length": 3,
            "first": False,
            "last": False,
            "classifier_id": 2,  # Custom param
        }

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="test_agent",
            agent_config={"agent_type": "test"},
            version_context=version_context,
        )

        # Version namespace should be present (not "loop")
        assert "version" in field_context
        assert field_context["version"]["length"] == 3
        assert field_context["version"]["first"] is False
        assert field_context["version"]["last"] is False

        # Top-level convenience variables should be present
        assert field_context["i"] == 2
        assert field_context["idx"] == 1

        # Custom param should be at top level
        assert field_context["classifier_id"] == 2

    def test_top_level_variables_for_jinja2(self):
        """Verify {{ i }} and {{ idx }} work at top level (not just {{ version.i }})."""
        from agent_actions.prompt.context.scope import ContextScopeProcessor

        version_context = {
            "i": 1,
            "idx": 0,
            "length": 3,
            "first": True,
            "last": False,
        }

        field_context = ContextScopeProcessor.build_field_context_with_history(
            contents={},
            agent_name="test_agent",
            agent_config={"agent_type": "test"},
            version_context=version_context,
        )

        # These enable {{ i }} and {{ idx }} in Jinja2 templates
        assert "i" in field_context
        assert "idx" in field_context
        assert field_context["i"] == 1
        assert field_context["idx"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
