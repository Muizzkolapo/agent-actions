"""Regression: _save_failed_render propagates OSError instead of swallowing it.

Finding #7: render_workflow.py:92 — OSError on render save was silently returned
as "" (empty string). Callers had no way to detect the failure. The fix removes
the silent fallback so OSError propagates, and the caller logs a warning while
still raising the original ConfigurationError.
"""

from unittest.mock import patch

import pytest

from agent_actions.prompt.render_workflow import _save_failed_render


class TestSaveFailedRenderPropagatesOSError:
    """_save_failed_render must raise OSError, not return ''."""

    def test_oserror_on_write_propagates(self, tmp_path):
        """OSError during file write is not caught — it propagates to caller."""
        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()
        read_only_dir.chmod(0o444)

        with patch(
            "agent_actions.prompt.render_workflow.resolve_project_root",
            return_value=read_only_dir,
        ):
            with pytest.raises(OSError):
                _save_failed_render("bad yaml", "test_workflow", project_root=read_only_dir)

        read_only_dir.chmod(0o755)

    def test_successful_save_returns_path_message(self, tmp_path):
        """When save succeeds, returns message with file path and debug command."""
        with patch(
            "agent_actions.prompt.render_workflow.resolve_project_root",
            return_value=tmp_path,
        ):
            result = _save_failed_render("bad yaml", "my_workflow", project_root=tmp_path)

        assert "my_workflow_failed.yml" in result
        assert "agac inspect -a my_workflow --yaml" in result


class TestRenderPipelineYamlParseErrorWithSaveFailure:
    """When YAML parse fails AND save fails, ConfigurationError is still raised."""

    def test_yaml_error_raised_even_if_save_fails(self, tmp_path):
        """ConfigurationError from YAML parse is not lost when debug save fails."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.render_workflow import render_pipeline_with_templates

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        yaml_file = tmp_path / "bad.yml"
        yaml_file.write_text("name: test\nprompt: hello", encoding="utf-8")

        config_content = "name: test\nbad_yaml: [unclosed"
        yaml_file.write_text(config_content, encoding="utf-8")

        with patch(
            "agent_actions.prompt.render_workflow._save_failed_render",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(ConfigurationError, match="Error parsing YAML"):
                render_pipeline_with_templates(yaml_file, templates_dir, project_root=tmp_path)

    def test_yaml_error_includes_save_path_when_save_succeeds(self, tmp_path):
        """ConfigurationError message includes debug file path on successful save."""
        from agent_actions.errors import ConfigurationError
        from agent_actions.prompt.render_workflow import render_pipeline_with_templates

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        yaml_file = tmp_path / "bad.yml"
        yaml_file.write_text("bad_yaml: [unclosed", encoding="utf-8")

        with pytest.raises(ConfigurationError, match="Rendered output saved to"):
            render_pipeline_with_templates(yaml_file, templates_dir, project_root=tmp_path)
