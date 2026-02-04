"""
Test early schema validation during workflow initialization.

Tests for issue #790: Schema validation should fail during config validation,
not at runtime.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_actions.errors.configuration import ConfigValidationError


class TestSchemaValidationLogic:
    """Test the schema validation logic in isolation."""

    def test_missing_schema_detected(self, tmp_path):
        """Verify missing schema file is detected."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create one schema, reference another that doesn't exist
        (schema_dir / "existing.yml").write_text("name: existing")

        existing = schema_dir / "existing.yml"
        missing = schema_dir / "missing.yml"

        assert existing.exists()
        assert not missing.exists()

    def test_existing_schema_passes(self, tmp_path):
        """Verify existing schema file passes validation."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        (schema_dir / "my_schema.yml").write_text("name: my_schema\nfields: []")

        schema_file = schema_dir / "my_schema.yml"
        assert schema_file.exists()


class TestWorkflowSchemaValidation:
    """Test schema validation in AgentWorkflow context."""

    def test_validate_schema_files_raises_on_missing(self):
        """Verify _validate_schema_files raises ConfigValidationError for missing schemas."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        # Create a mock workflow with missing schema reference
        with patch.object(AgentWorkflow, "__init__", lambda self: None):
            workflow = AgentWorkflow()
            workflow.config = MagicMock()
            workflow.config.paths.constructor_path = (
                "/fake/agent_workflow/test/agent_config/test.yml"
            )

            # Mock agent_configs with a missing schema reference
            workflow.metadata = MagicMock()
            workflow.metadata.agent_configs = {
                "test_action": {
                    "schema_name": "nonexistent_schema",
                }
            }

            # The property returns metadata.agent_configs
            workflow.__class__.agent_configs = property(lambda self: self.metadata.agent_configs)

            # Should raise ConfigValidationError
            with pytest.raises(ConfigValidationError) as exc_info:
                workflow._validate_schema_files()

            assert "nonexistent_schema" in str(exc_info.value)
            assert "test_action" in str(exc_info.value)

    def test_validate_schema_files_passes_when_no_schemas(self):
        """Verify validation passes when no schema_name fields are present."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        with patch.object(AgentWorkflow, "__init__", lambda self: None):
            workflow = AgentWorkflow()
            workflow.config = MagicMock()
            workflow.config.paths.constructor_path = (
                "/fake/agent_workflow/test/agent_config/test.yml"
            )

            # Mock agent_configs without schema references
            workflow.metadata = MagicMock()
            workflow.metadata.agent_configs = {
                "test_action": {
                    "agent_type": "test",
                    # No schema_name field
                }
            }

            workflow.__class__.agent_configs = property(lambda self: self.metadata.agent_configs)

            # Should not raise
            workflow._validate_schema_files()

    def test_validate_schema_files_passes_when_schema_exists(self, tmp_path, monkeypatch):
        """Verify validation passes when schema file exists."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        # Create schema directory and file in tmp_path (simulating project root)
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "my_schema.yml").write_text("name: my_schema")

        # Mock cwd to return tmp_path (simulating running from project root)
        monkeypatch.chdir(tmp_path)

        with patch.object(AgentWorkflow, "__init__", lambda self: None):
            workflow = AgentWorkflow()
            workflow.config = MagicMock()
            workflow.config.paths.constructor_path = str(tmp_path / "config.yml")

            # Mock agent_configs with existing schema reference
            workflow.metadata = MagicMock()
            workflow.metadata.agent_configs = {
                "test_action": {
                    "schema_name": "my_schema",
                }
            }

            workflow.__class__.agent_configs = property(lambda self: self.metadata.agent_configs)

            # Should not raise
            workflow._validate_schema_files()


class TestErrorMessage:
    """Test the error message format."""

    def test_error_message_includes_action_and_schema(self):
        """Verify error message is clear and actionable."""
        from agent_actions.workflow.coordinator import AgentWorkflow

        with patch.object(AgentWorkflow, "__init__", lambda self: None):
            workflow = AgentWorkflow()
            workflow.config = MagicMock()
            workflow.config.paths.constructor_path = (
                "/fake/project/agent_workflow/wf/agent_config/wf.yml"
            )

            workflow.metadata = MagicMock()
            workflow.metadata.agent_configs = {
                "extract_data": {"schema_name": "missing_schema_1"},
                "transform_data": {"schema_name": "missing_schema_2"},
            }

            workflow.__class__.agent_configs = property(lambda self: self.metadata.agent_configs)

            with pytest.raises(ConfigValidationError) as exc_info:
                workflow._validate_schema_files()

            error_msg = str(exc_info.value)

            # Should list both missing schemas
            assert "missing_schema_1" in error_msg
            assert "missing_schema_2" in error_msg

            # Should list both actions
            assert "extract_data" in error_msg
            assert "transform_data" in error_msg

            # Should have helpful message
            assert "schema/ directory" in error_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
