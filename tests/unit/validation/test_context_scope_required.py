"""Tests for context_scope required validation in WorkflowStaticAnalyzer."""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


class TestContextScopeRequired:
    """Verify static analysis catches missing context_scope."""

    def _make_workflow(self, actions):
        return {"name": "test", "actions": actions}

    def test_action_without_context_scope_produces_error(self):
        """Action missing context_scope should produce a StaticTypeError."""
        workflow = self._make_workflow(
            [
                {"name": "my_action", "prompt": "do something"},
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        errors = [e for e in result.errors if "no context_scope" in e.message]
        assert len(errors) == 1
        assert "my_action" in errors[0].message

    def test_action_with_context_scope_passes(self):
        """Action with context_scope should not produce a missing-scope error."""
        workflow = self._make_workflow(
            [
                {
                    "name": "my_action",
                    "prompt": "do something",
                    "context_scope": {"observe": ["source.text"]},
                },
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        scope_errors = [e for e in result.errors if "no context_scope" in e.message]
        assert len(scope_errors) == 0

    def test_action_with_empty_context_scope_produces_error(self):
        """Empty dict context_scope should produce error."""
        workflow = self._make_workflow(
            [
                {"name": "my_action", "prompt": "do something", "context_scope": {}},
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        errors = [e for e in result.errors if "no context_scope" in e.message]
        assert len(errors) == 1

    def test_multiple_actions_each_validated(self):
        """Each action without context_scope should produce its own error."""
        workflow = self._make_workflow(
            [
                {"name": "action_a", "prompt": "a"},
                {"name": "action_b", "prompt": "b", "context_scope": {"observe": ["source.*"]}},
                {"name": "action_c", "prompt": "c"},
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        scope_errors = [e for e in result.errors if "no context_scope" in e.message]
        names = {e.location.agent_name for e in scope_errors}
        assert "action_a" in names
        assert "action_b" not in names
        assert "action_c" in names

    def test_error_has_helpful_hint(self):
        """Error should include a hint about how to fix."""
        workflow = self._make_workflow(
            [
                {"name": "my_action", "prompt": "do something"},
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        errors = [e for e in result.errors if "no context_scope" in e.message]
        assert errors[0].hint is not None
        assert "context_scope" in errors[0].hint

    def test_null_context_scope_detected(self):
        """YAML null context_scope (indentation error) should produce error."""
        workflow = self._make_workflow(
            [
                {"name": "broken", "prompt": "do something", "context_scope": None},
            ]
        )
        analyzer = WorkflowStaticAnalyzer(workflow)
        result = analyzer.analyze()

        errors = [e for e in result.errors if "no context_scope" in e.message]
        assert len(errors) == 1
        assert "broken" in errors[0].message

    def test_null_context_scope_with_orphaned_observe_caught_by_normalizer(self):
        """When observe is a sibling of null context_scope, the runtime normalizer
        catches it with an indentation error. The static analyzer normalizes null
        to {} and reports 'no context_scope' (the indentation hint is in the
        normalizer's ConfigurationError, not here)."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.input.context.normalizer import normalize_all_agent_configs

        import pytest

        agent_configs = {
            "misindented": {
                "name": "misindented",
                "context_scope": None,
                "observe": ["source.*"],
            }
        }
        with pytest.raises(ConfigurationError, match="indentation"):
            normalize_all_agent_configs(agent_configs)
