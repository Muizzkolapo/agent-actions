"""Tests for version context injection in versioned actions.

This tests the fix for version template variables ({{ i }}, {{ loop.length }}, etc.)
being available in prompt store references.
"""

import pytest

from agent_actions.output.response.expander import ActionExpander


class TestVersionContextCompilation:
    """Test suite for _version_context compilation during expansion."""

    @staticmethod
    def _expand_versioned(versions_config, action_name="process"):
        """Helper to expand a single versioned action and return agents."""
        config = {
            "name": "test_workflow",
            "description": "Test workflow",
            "version": "1.0.0",
            "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini"},
            "actions": [
                {
                    "name": action_name,
                    "intent": f"{action_name.title()} action",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": f"{action_name.title()}",
                    "versions": versions_config,
                }
            ],
            "plan": [action_name],
        }
        result = ActionExpander.expand_actions_to_agents(config)
        return result["test_workflow"]

    def test_version_context_added_to_agent_config(self):
        """Verify _version_context is added to each versioned agent."""
        agents = self._expand_versioned({"range": [1, 3], "mode": "parallel"}, "classify")
        assert len(agents) == 3
        for agent in agents:
            assert "_version_context" in agent
            assert isinstance(agent["_version_context"], dict)

    def test_version_context_has_i_and_idx(self):
        """Verify _version_context contains i (iteration value) and idx (zero-based index)."""
        agents = self._expand_versioned({"range": [1, 3]})
        assert agents[0]["_version_context"]["i"] == 1
        assert agents[0]["_version_context"]["idx"] == 0
        assert agents[1]["_version_context"]["i"] == 2
        assert agents[1]["_version_context"]["idx"] == 1
        assert agents[2]["_version_context"]["i"] == 3
        assert agents[2]["_version_context"]["idx"] == 2

    def test_version_context_has_length(self):
        """Verify _version_context contains length (total iterations)."""
        agents = self._expand_versioned({"range": [1, 5]}, "extract")
        for agent in agents:
            assert agent["_version_context"]["length"] == 5

    def test_version_context_has_first_and_last_flags(self):
        """Verify _version_context contains first and last boolean flags."""
        agents = self._expand_versioned({"range": [1, 3]}, "analyze")
        assert agents[0]["_version_context"]["first"] is True
        assert agents[0]["_version_context"]["last"] is False
        assert agents[1]["_version_context"]["first"] is False
        assert agents[1]["_version_context"]["last"] is False
        assert agents[2]["_version_context"]["first"] is False
        assert agents[2]["_version_context"]["last"] is True

    def test_version_context_single_iteration(self):
        """Verify first and last are both True for single iteration."""
        agents = self._expand_versioned({"range": [1, 1]}, "single")
        assert len(agents) == 1
        assert agents[0]["_version_context"]["first"] is True
        assert agents[0]["_version_context"]["last"] is True
        assert agents[0]["_version_context"]["length"] == 1

    def test_custom_param_name_in_version_context(self):
        """Verify custom param names are included in version context."""
        agents = self._expand_versioned({"param": "classifier_id", "range": [1, 3]}, "classify")
        assert agents[0]["_version_context"]["classifier_id"] == 1
        assert agents[1]["_version_context"]["classifier_id"] == 2
        assert agents[2]["_version_context"]["classifier_id"] == 3
        assert agents[0]["_version_context"]["i"] == 1
        assert agents[1]["_version_context"]["i"] == 2
        assert agents[2]["_version_context"]["i"] == 3

    def test_default_param_name_not_duplicated(self):
        """Verify default param 'i' doesn't create duplicate entry."""
        agents = self._expand_versioned({"param": "i", "range": [1, 2]})
        version_context = agents[0]["_version_context"]
        expected_keys = {"i", "idx", "length", "first", "last"}
        assert set(version_context.keys()) == expected_keys

    def test_version_context_with_explicit_list_range(self):
        """Verify version context works with explicit list ranges."""
        agents = self._expand_versioned({"range": [10, 20, 30]})
        assert len(agents) == 3
        assert agents[0]["_version_context"]["i"] == 10
        assert agents[1]["_version_context"]["i"] == 20
        assert agents[2]["_version_context"]["i"] == 30
        assert agents[0]["_version_context"]["idx"] == 0
        assert agents[1]["_version_context"]["idx"] == 1
        assert agents[2]["_version_context"]["idx"] == 2
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
        from agent_actions.prompt.context.scope_builder import build_field_context_with_history

        version_context = {
            "i": 2,
            "idx": 1,
            "length": 3,
            "first": False,
            "last": False,
            "classifier_id": 2,
        }

        field_context = build_field_context_with_history(
            agent_name="test_agent",
            agent_config={"agent_type": "test"},
            version_context=version_context,
        )

        assert "version" in field_context
        assert field_context["version"]["length"] == 3
        assert field_context["version"]["first"] is False
        assert field_context["version"]["last"] is False
        assert field_context["i"] == 2
        assert field_context["idx"] == 1
        assert field_context["classifier_id"] == 2

    def test_top_level_variables_for_jinja2(self):
        """Verify {{ i }} and {{ idx }} work at top level (not just {{ version.i }})."""
        from agent_actions.prompt.context.scope_builder import build_field_context_with_history

        version_context = {
            "i": 1,
            "idx": 0,
            "length": 3,
            "first": True,
            "last": False,
        }

        field_context = build_field_context_with_history(
            agent_name="test_agent",
            agent_config={"agent_type": "test"},
            version_context=version_context,
        )

        assert "i" in field_context
        assert "idx" in field_context
        assert field_context["i"] == 1
        assert field_context["idx"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
