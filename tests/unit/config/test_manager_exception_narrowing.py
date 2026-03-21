"""Regression tests for narrowed exception handling in ConfigManager.get_user_agents().

Covers the exception paths introduced when replacing broad `except Exception`
with specific handlers for project defaults loading.
"""

from unittest.mock import patch

import pytest
import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.config.paths import ProjectRootNotFoundError
from agent_actions.errors import ConfigurationError, ConfigValidationError


class TestGetUserAgentsExceptionNarrowing:
    """Verify narrowed exception handling in get_user_agents()."""

    def _make_workflow_manager(self, tmp_path):
        """Create a ConfigManager with a workflow-style config (has 'name' and 'actions')."""
        cfg = tmp_path / "workflow.yml"
        cfg.write_text(
            "name: test_workflow\n"
            "description: test workflow\n"
            "version: '1.0'\n"
            "actions:\n"
            "  - name: extract\n"
            "    intent: extract data\n"
            "    kind: llm\n"
        )
        default = tmp_path / "default.yml"
        default.write_text("{}")
        # Template dir needed by load_configs
        (tmp_path / "templates").mkdir()
        cm = ConfigManager(str(cfg), str(default), project_root=tmp_path)
        cm.load_configs()
        return cm

    def test_project_root_not_found_uses_empty_defaults(self, tmp_path):
        """ProjectRootNotFoundError → silently use empty defaults (no crash)."""
        cm = self._make_workflow_manager(tmp_path)

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch(
                "agent_actions.output.response.expander.ActionExpander.expand_actions_to_agents",
                return_value={"test_workflow": [{"agent_type": "extract"}]},
            ),
        ):
            mock_pm_cls.return_value.get_project_root.side_effect = (
                ProjectRootNotFoundError("no root")
            )
            # Should not raise — falls back to empty project_defaults
            result = cm.get_user_agents()

        assert isinstance(result, list)

    def test_file_not_found_uses_empty_defaults(self, tmp_path):
        """FileNotFoundError from load_project_config → empty defaults."""
        cm = self._make_workflow_manager(tmp_path)

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config") as mock_load,
            patch(
                "agent_actions.output.response.expander.ActionExpander.expand_actions_to_agents",
                return_value={"test_workflow": [{"agent_type": "extract"}]},
            ),
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            mock_load.side_effect = FileNotFoundError("no config file")

            result = cm.get_user_agents()

        assert isinstance(result, list)

    def test_yaml_error_raises_configuration_error(self, tmp_path):
        """yaml.YAMLError → ConfigurationError with context."""
        cm = self._make_workflow_manager(tmp_path)

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config") as mock_load,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            mock_load.side_effect = yaml.YAMLError("bad yaml")

            with pytest.raises(ConfigurationError, match="Failed to load project defaults"):
                cm.get_user_agents()

    def test_os_error_raises_configuration_error(self, tmp_path):
        """OSError → ConfigurationError with context."""
        cm = self._make_workflow_manager(tmp_path)

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config") as mock_load,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            mock_load.side_effect = PermissionError("access denied")

            with pytest.raises(ConfigurationError, match="Failed to load project defaults"):
                cm.get_user_agents()

    def test_config_validation_error_raises_configuration_error(self, tmp_path):
        """ConfigValidationError from load_project_config → ConfigurationError."""
        cm = self._make_workflow_manager(tmp_path)

        with (
            patch("agent_actions.config.manager.PathManager") as mock_pm_cls,
            patch("agent_actions.config.manager.load_project_config") as mock_load,
        ):
            mock_pm_cls.return_value.get_project_root.return_value = tmp_path
            mock_load.side_effect = ConfigValidationError("invalid config")

            with pytest.raises(ConfigurationError, match="Failed to load project defaults"):
                cm.get_user_agents()
