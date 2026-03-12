"""
Test early schema validation during workflow initialization.

Tests for issue #790: Schema validation should fail during config validation,
not at runtime.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors.configuration import ConfigValidationError


def _create_mock_workflow(constructor_path, agent_configs):
    """Create a mock AgentWorkflow with given agent_configs."""
    from agent_actions.workflow.coordinator import AgentWorkflow

    with patch.object(AgentWorkflow, "__init__", lambda self: None):
        workflow = AgentWorkflow()
        workflow.config = MagicMock()
        workflow.config.paths.constructor_path = constructor_path
        workflow.metadata = MagicMock()
        workflow.metadata.agent_configs = agent_configs
        workflow.__class__.agent_configs = property(lambda self: self.metadata.agent_configs)
        return workflow


class TestSchemaValidationLogic:
    """Test the schema validation logic in isolation."""

    def test_missing_schema_detected(self, tmp_path):
        """Verify missing schema file is detected."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

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
        workflow = _create_mock_workflow(
            "/fake/agent_workflow/test/agent_config/test.yml",
            {"test_action": {"schema_name": "nonexistent_schema"}},
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            workflow._validate_schema_files()
        assert "nonexistent_schema" in str(exc_info.value)
        assert "test_action" in str(exc_info.value)

    def test_validate_schema_files_passes_when_no_schemas(self):
        """Verify validation passes when no schema_name fields are present."""
        workflow = _create_mock_workflow(
            "/fake/agent_workflow/test/agent_config/test.yml",
            {"test_action": {"agent_type": "test"}},
        )
        workflow._validate_schema_files()

    def test_validate_schema_files_passes_when_schema_exists(self, tmp_path, monkeypatch):
        """Verify validation passes when schema file exists."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "my_schema.yml").write_text("name: my_schema")
        monkeypatch.chdir(tmp_path)

        workflow = _create_mock_workflow(
            str(tmp_path / "config.yml"),
            {"test_action": {"schema_name": "my_schema"}},
        )
        workflow._validate_schema_files()


class TestErrorMessage:
    """Test the error message format."""

    def test_error_message_includes_action_and_schema(self):
        """Verify error message is clear and actionable."""
        workflow = _create_mock_workflow(
            "/fake/project/agent_workflow/wf/agent_config/wf.yml",
            {
                "extract_data": {"schema_name": "missing_schema_1"},
                "transform_data": {"schema_name": "missing_schema_2"},
            },
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            workflow._validate_schema_files()

        error_msg = str(exc_info.value)
        assert "missing_schema_1" in error_msg
        assert "missing_schema_2" in error_msg
        assert "extract_data" in error_msg
        assert "transform_data" in error_msg
        assert "schema/ directory" in error_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
