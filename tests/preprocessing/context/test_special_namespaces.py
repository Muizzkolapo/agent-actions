"""
Tests for special namespace support (source, loop, workflow).

Tests that special reserved namespaces are properly recognized and handled
differently from regular workflow actions.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies


class TestSpecialNamespaceValidationBypass:
    """Test that special namespaces bypass action existence validation."""

    def test_source_namespace_bypasses_validation(self):
        """Test that 'source' namespace doesn't require workflow action."""
        action_config = {
            "dependencies": [],
            "context_scope": {
                "observe": [
                    "source.page_content",  # Special namespace
                    "source.title",
                ]
            },
        }
        workflow_actions = ["other_action"]  # 'source' not in workflow

        # Should NOT raise ConfigurationError
        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "test_action"
        )

        assert "source" in context_sources

    def test_workflow_namespace_bypasses_validation(self):
        """Test that 'workflow' namespace doesn't require workflow action."""
        action_config = {
            "dependencies": [],
            "context_scope": {
                "observe": [
                    "workflow.name",
                    "workflow.version",
                ]
            },
        }
        workflow_actions = ["other_action"]  # 'workflow' not in workflow

        # Should NOT raise ConfigurationError
        input_sources, context_sources = infer_dependencies(
            action_config, workflow_actions, "test_action"
        )

        assert "workflow" in context_sources

    def test_unknown_namespace_still_raises_error(self):
        """Test that unknown namespaces (not in SPECIAL_NAMESPACES) still fail."""
        action_config = {
            "dependencies": [],
            "context_scope": {
                "observe": [
                    "unknown_action.field",  # Not special, not in workflow
                ]
            },
        }
        workflow_actions = ["other_action"]

        # Should raise ConfigurationError for unknown action
        with pytest.raises(ConfigurationError) as exc_info:
            infer_dependencies(action_config, workflow_actions, "test_action")

        assert "unknown_action" in str(exc_info.value)
        assert "not found in workflow" in str(exc_info.value)


# NOTE: TestEnrichSourceNamespace was removed when ``source`` was hoisted out of
# ``content`` and onto the record envelope as a tracking field. The bus reads
# source from ``record["source"]`` directly — no fallback synthesis from
# ``current_item["content"]`` is needed or wanted. See the regression test
# ``tests/regression/test_source_namespace_hoist.py`` for the new model.
