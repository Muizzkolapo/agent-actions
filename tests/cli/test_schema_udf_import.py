"""Tests for CLI schema command UDF registry import error surfacing."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.cli.schema import SchemaCommand
from agent_actions.errors import DependencyError


class TestUDFRegistryImportError:
    """Verify broken UDF registry import surfaces a DependencyError."""

    @patch("agent_actions.cli.schema.AgentWorkflow")
    @patch("agent_actions.cli.schema.ConfigRenderingService.render_and_load_config")
    @patch("agent_actions.cli.schema.find_config_file", return_value="/fake/config.yml")
    @patch("agent_actions.cli.schema.ProjectPathsFactory.create_project_paths")
    def test_import_error_raises_dependency_error(
        self,
        mock_paths_factory,
        mock_find_config,
        mock_render,
        mock_workflow,
    ):
        """ImportError from UDF registry must raise DependencyError, not pass silently."""
        mock_paths = MagicMock()
        mock_paths.agent_config_dir = "/fake/agent_config"
        mock_paths.template_dir = "/fake/templates"
        mock_paths.default_config_path = "/fake/defaults.yml"
        mock_paths.current_dir = "/fake"
        mock_paths.schema_dir = "/fake/schemas"
        mock_paths_factory.return_value = mock_paths

        mock_workflow_instance = MagicMock()
        mock_workflow_instance.action_configs = {"action1": {"kind": "llm"}}
        mock_workflow.return_value = mock_workflow_instance

        command = SchemaCommand(
            agent="test_agent",
            user_code=None,
            json_output=False,
            verbose=False,
        )

        with (
            patch.dict(
                "sys.modules",
                {"agent_actions.utils.udf_management.registry": None},
            ),
            pytest.raises(DependencyError, match="Failed to import UDF registry"),
        ):
            command.execute()

    @patch("agent_actions.cli.schema.WorkflowSchemaService")
    @patch("agent_actions.cli.schema.SchemaLoader")
    @patch("agent_actions.cli.schema.AgentWorkflow")
    @patch("agent_actions.cli.schema.ConfigRenderingService.render_and_load_config")
    @patch("agent_actions.cli.schema.find_config_file", return_value="/fake/config.yml")
    @patch("agent_actions.cli.schema.ProjectPathsFactory.create_project_paths")
    def test_successful_import_proceeds_normally(
        self,
        mock_paths_factory,
        mock_find_config,
        mock_render,
        mock_workflow,
        mock_schema_loader,
        mock_schema_service,
    ):
        """Successful UDF registry import should proceed without error."""
        mock_paths = MagicMock()
        mock_paths.agent_config_dir = "/fake/agent_config"
        mock_paths.template_dir = "/fake/templates"
        mock_paths.default_config_path = "/fake/defaults.yml"
        mock_paths.current_dir = "/fake"
        mock_paths.schema_dir = "/fake/schemas"
        mock_paths_factory.return_value = mock_paths

        mock_workflow_instance = MagicMock()
        mock_workflow_instance.action_configs = {"action1": {"kind": "llm"}}
        mock_workflow_instance.execution_order = ["action1"]
        mock_workflow.return_value = mock_workflow_instance

        mock_service_instance = MagicMock()
        mock_service_instance.get_all_schemas.return_value = {}
        mock_schema_service.return_value = mock_service_instance

        command = SchemaCommand(
            agent="test_agent",
            user_code=None,
            json_output=True,
            verbose=False,
        )

        # Should not raise — UDF registry import succeeds normally
        command.execute()

        # Verify UDF_REGISTRY was passed through to WorkflowSchemaService
        call_kwargs = mock_schema_service.call_args[1]
        assert "udf_registry" in call_kwargs
        assert isinstance(call_kwargs["udf_registry"], dict)
