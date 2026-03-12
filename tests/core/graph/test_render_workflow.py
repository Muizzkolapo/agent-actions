"""
Tests for render_workflow.py - Jinja2 template rendering.

This module tests:
1. Failed render caching
2. Jinja2 variable substitution
3. Backward compatibility
"""

import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


class TestFailedRenderCache:
    """Test failed render caching functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / "templates"
        self.templates_folder.mkdir()
        self.project_root = Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_failed_render_saved_to_cache(self):
        """Test that failed YAML renders are saved to cache."""
        yaml_file = Path(self.temp_dir) / "broken_workflow.yml"
        yaml_file.write_text(
            "\nname: broken\nactions:\n  - name: test\n    : invalid_yaml_syntax_here\n"
        )
        cache_dir = self.project_root / ".agent-actions" / "cache" / "rendered_workflows"
        expected_cache_file = cache_dir / "broken_workflow_failed.yml"
        with pytest.raises(ConfigurationError):
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder),
                project_root=self.project_root,
            )
        assert expected_cache_file.exists()
        cached_content = expected_cache_file.read_text()
        assert "invalid_yaml_syntax_here" in cached_content

    def test_error_message_includes_cache_path(self):
        """Test that error message shows cache file path."""
        yaml_file = Path(self.temp_dir) / "broken_workflow.yml"
        yaml_file.write_text("\nname: broken\nactions:\n  - invalid: [unclosed bracket\n")
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder),
                project_root=self.project_root,
            )
        error_message = str(exc_info.value)
        assert ".agent-actions/cache/rendered_workflows" in error_message
        assert "broken_workflow_failed.yml" in error_message

    def test_error_message_suggests_render_command(self):
        """Test that error message suggests using render command."""
        yaml_file = Path(self.temp_dir) / "test_workflow.yml"
        yaml_file.write_text("\nactions:\n  - : broken\n")
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder),
                project_root=self.project_root,
            )
        error_message = str(exc_info.value)
        assert "agac render" in error_message
        assert "test_workflow" in error_message

    def test_cache_directory_created_automatically(self):
        """Test that cache directory is created if it doesn't exist."""
        cache_dir = self.project_root / ".agent-actions" / "cache" / "rendered_workflows"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        yaml_file = Path(self.temp_dir) / "workflow.yml"
        yaml_file.write_text("invalid: [yaml")
        with pytest.raises(ConfigurationError):
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder),
                project_root=self.project_root,
            )
        assert cache_dir.exists()
        assert cache_dir.is_dir()


class TestRenderPipelineIntegration:
    """Integration tests for render_pipeline_with_templates."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / "templates"
        self.templates_folder.mkdir()

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_jinja2_variable_substitution(self):
        """Test that Jinja2 variable substitution works with normalization."""
        yaml_file = Path(self.temp_dir) / "workflow.yml"
        yaml_file.write_text(
            "\n      {% set workflow_name = 'combined_test' %}\n      name: {{ workflow_name }}\n      version: 1.0\n      actions:\n        - name: action1\n          kind: action\n"
        )
        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file), templates_folder=str(self.templates_folder)
        )
        parsed = yaml.safe_load(result)
        assert parsed["name"] == "combined_test"
        assert "actions" in parsed
        assert len(parsed["actions"]) == 1

    def test_backward_compatibility_correct_templates(self):
        """Test that correctly formatted templates still work."""
        yaml_file = Path(self.temp_dir) / "workflow.yml"
        yaml_file.write_text(
            "\nname: test_workflow\nversion: 1.0\nactions:\n  - name: test_action\n    kind: action\n    inputs:\n      param1: value1\n"
        )
        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file), templates_folder=str(self.templates_folder)
        )
        parsed = yaml.safe_load(result)
        assert parsed["name"] == "test_workflow"
        assert parsed["version"] == 1.0
        assert len(parsed["actions"]) == 1
        assert parsed["actions"][0]["name"] == "test_action"
