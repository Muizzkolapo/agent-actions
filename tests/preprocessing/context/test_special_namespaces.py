"""
Tests for special namespace support (source, loop, workflow).

Tests that special reserved namespaces are properly recognized and handled
differently from regular workflow actions.
"""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.context.scope_inference import infer_dependencies
from agent_actions.prompt.context.scope_namespace import _enrich_source_namespace


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


class TestEnrichSourceNamespace:
    """Test _enrich_source_namespace() fallback logic."""

    def test_enrich_source_namespace_no_current_item(self):
        """Test with no current item returns base namespace unchanged."""
        base_namespace = {"existing": "value"}
        current_item = None

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result == {"existing": "value"}

    def test_enrich_source_namespace_empty_current_item(self):
        """Test with empty current item returns base namespace unchanged."""
        base_namespace = {"existing": "value"}
        current_item = {}

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result == {"existing": "value"}

    def test_enrich_source_namespace_adds_missing_fields(self):
        """Test that fallback fields are added from current item."""
        base_namespace = {"source_guid": "guid-123"}
        current_item = {
            "content": {"page_content": "Full text here", "title": "My Title"},
            "source_guid": "guid-123",
        }

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result["source_guid"] == "guid-123"  # Original preserved
        assert result["page_content"] == "Full text here"  # Added from current
        assert result["title"] == "My Title"  # Added from current

    def test_enrich_source_namespace_does_not_overwrite_existing(self):
        """Test that existing fields in base namespace are NOT overwritten."""
        base_namespace = {"page_content": "Original content", "source_guid": "guid-123"}
        current_item = {"content": {"page_content": "Different content", "extra": "value"}}

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result["page_content"] == "Original content"  # NOT overwritten
        assert result["extra"] == "value"  # Added
        assert result["source_guid"] == "guid-123"  # Preserved

    def test_enrich_source_namespace_with_flat_structure(self):
        """Test with flat current item structure (no 'content' key)."""
        base_namespace = {}
        current_item = {"page_content": "Text", "title": "Title", "id": "123"}

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result["page_content"] == "Text"
        assert result["title"] == "Title"
        assert result["id"] == "123"

    def test_enrich_source_namespace_handles_none_base(self):
        """Test with None base namespace (should create new dict)."""
        base_namespace = None
        current_item = {"content": {"field": "value"}}

        result = _enrich_source_namespace(base_namespace, current_item)

        assert result == {"field": "value"}
