"""Tests for _load_single_config error paths in ConfigManager.

Covers:
- TemplateRenderingError → ConfigurationError with Path-based config name
- yaml.YAMLError → ConfigurationError with correct context
- Generic Exception → ConfigurationError with type name and message
- ConfigurationError passthrough (no double-wrap)
"""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import ConfigurationError, TemplateRenderingError


def _make_manager(tmp_path: Path) -> ConfigManager:
    """Create a ConfigManager with minimal paths."""
    config_file = tmp_path / "workflow.yml"
    config_file.write_text("name: test\n")
    default_file = tmp_path / "default.yml"
    default_file.write_text("{}\n")
    (tmp_path / "templates").mkdir(exist_ok=True)
    return ConfigManager(str(config_file), str(default_file), project_root=tmp_path)


class TestLoadSingleConfigErrors:
    """Verify _load_single_config error paths use Path().name, not str.name."""

    def test_template_rendering_error_includes_filename(self, tmp_path):
        """TemplateRenderingError should produce config name from Path, not crash."""
        manager = _make_manager(tmp_path)
        config_path = str(tmp_path / "workflow.yml")

        with patch(
            "agent_actions.prompt.render_workflow.render_pipeline_with_templates",
            side_effect=TemplateRenderingError("bad template"),
        ):
            with pytest.raises(ConfigurationError, match="workflow.yml") as exc_info:
                manager._load_single_config(config_path, "workflow")

        assert exc_info.value.context["operation"] == "template_rendering"
        assert "config_path" in exc_info.value.context

    def test_yaml_error_includes_filename(self, tmp_path):
        """yaml.YAMLError should produce config name from Path, not crash."""
        manager = _make_manager(tmp_path)
        config_path = str(tmp_path / "workflow.yml")

        with patch(
            "agent_actions.prompt.render_workflow.render_pipeline_with_templates",
            return_value="not: [valid: yaml: {{",
        ):
            with patch("agent_actions.config.manager.yaml.safe_load") as mock_load:
                mock_load.side_effect = yaml.YAMLError("invalid yaml")
                with pytest.raises(ConfigurationError, match="workflow.yml") as exc_info:
                    manager._load_single_config(config_path, "workflow")

        assert exc_info.value.context["operation"] == "parse_yaml"

    def test_generic_exception_includes_type_and_filename(self, tmp_path):
        """Generic Exception should include type(e).__name__ and config filename."""
        manager = _make_manager(tmp_path)
        config_path = str(tmp_path / "workflow.yml")

        with patch(
            "agent_actions.prompt.render_workflow.render_pipeline_with_templates",
            side_effect=RuntimeError("disk full"),
        ):
            with pytest.raises(
                ConfigurationError, match=r"RuntimeError.*disk full"
            ) as exc_info:
                manager._load_single_config(config_path, "workflow")

        assert "workflow.yml" in str(exc_info.value)
        assert exc_info.value.context["operation"] == "load_workflow_config"

    def test_configuration_error_passes_through_without_wrapping(self, tmp_path):
        """ConfigurationError should re-raise directly — no double wrapping."""
        manager = _make_manager(tmp_path)
        config_path = str(tmp_path / "workflow.yml")
        inner = ConfigurationError("inner error", context={"inner": True})

        with patch(
            "agent_actions.prompt.render_workflow.render_pipeline_with_templates",
            side_effect=inner,
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                manager._load_single_config(config_path, "workflow")

        # Should be the original error, not wrapped in another ConfigurationError
        assert exc_info.value is inner
