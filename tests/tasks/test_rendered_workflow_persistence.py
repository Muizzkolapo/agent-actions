"""
Test that rendered workflows are persisted to cache directory.

This test ensures that the workflow rendering bug is fixed - rendered
workflows should be saved to .agent-actions/cache/rendered_workflows/
similar to how dbt compiles SQL to the compiled/ folder.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock

from agent_actions.tasks.services.config_renderer import JinjaTemplateRenderer


class TestRenderedWorkflowPersistence:
    """Test that rendered workflows are saved to cache directory."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.template_dir = Path(self.temp_dir) / 'templates'
        self.template_dir.mkdir()
        self.output_dir = Path(self.temp_dir) / 'rendered_workflows'

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_rendered_workflow_saved_to_cache(self):
        """Test that rendered workflows are written to output directory."""
        # Create test configuration
        config_file = Path(self.temp_dir) / 'test_workflow.yml'
        config_file.write_text("""
name: test_workflow
version: 1.0
actions:
  - name: test_action
    kind: action
""")

        renderer = JinjaTemplateRenderer()

        # Mock the render_pipeline_with_templates function
        with patch('agent_actions.tasks.services.config_renderer.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = "rendered: workflow content"

            # Render with output path
            result = renderer.render(
                config_path=str(config_file),
                template_dir=str(self.template_dir),
                output_path=str(self.output_dir)
            )

            # Verify rendered content is returned
            assert result == "rendered: workflow content"

            # Verify output directory was created
            assert self.output_dir.exists()
            assert self.output_dir.is_dir()

            # Verify rendered file was written
            expected_file = self.output_dir / 'test_workflow.yml'
            assert expected_file.exists()
            assert expected_file.read_text() == "rendered: workflow content"

    def test_rendered_workflow_not_saved_without_output_path(self):
        """Test that no file is written when output_path is not provided."""
        config_file = Path(self.temp_dir) / 'test_workflow.yml'
        config_file.write_text("name: test_workflow\nversion: 1.0")

        renderer = JinjaTemplateRenderer()

        with patch('agent_actions.tasks.services.config_renderer.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = "rendered content"

            # Render without output path
            result = renderer.render(
                config_path=str(config_file),
                template_dir=str(self.template_dir),
                output_path=None  # No output path
            )

            # Verify rendered content is returned
            assert result == "rendered content"

            # Verify no file was written (output_dir wasn't even created)
            assert not self.output_dir.exists()

    def test_multiple_workflows_rendered_to_same_directory(self):
        """Test that multiple workflows can be rendered to the same cache directory."""
        # Create multiple config files
        workflow_files = [
            ('workflow1.yml', 'name: workflow1\nversion: 1.0'),
            ('workflow2.yml', 'name: workflow2\nversion: 2.0'),
            ('workflow3.yml', 'name: workflow3\nversion: 3.0')
        ]

        renderer = JinjaTemplateRenderer()

        with patch('agent_actions.tasks.services.config_renderer.render_pipeline_with_templates') as mock_render:
            for filename, content in workflow_files:
                config_file = Path(self.temp_dir) / filename
                config_file.write_text(content)

                # Return different content for each workflow
                mock_render.return_value = f"rendered: {filename}"

                # Render to same output directory
                renderer.render(
                    config_path=str(config_file),
                    template_dir=str(self.template_dir),
                    output_path=str(self.output_dir)
                )

        # Verify all workflows were saved
        assert (self.output_dir / 'workflow1.yml').exists()
        assert (self.output_dir / 'workflow2.yml').exists()
        assert (self.output_dir / 'workflow3.yml').exists()

        # Verify each has correct content
        assert (self.output_dir / 'workflow1.yml').read_text() == "rendered: workflow1.yml"
        assert (self.output_dir / 'workflow2.yml').read_text() == "rendered: workflow2.yml"
        assert (self.output_dir / 'workflow3.yml').read_text() == "rendered: workflow3.yml"

    def test_rendered_workflow_overwrites_existing_file(self):
        """Test that re-rendering a workflow overwrites the existing cached file."""
        config_file = Path(self.temp_dir) / 'test_workflow.yml'
        config_file.write_text("name: test_workflow\nversion: 1.0")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create existing cached file with old content
        existing_file = self.output_dir / 'test_workflow.yml'
        existing_file.write_text("old rendered content")

        renderer = JinjaTemplateRenderer()

        with patch('agent_actions.tasks.services.config_renderer.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = "new rendered content"

            # Render workflow
            renderer.render(
                config_path=str(config_file),
                template_dir=str(self.template_dir),
                output_path=str(self.output_dir)
            )

            # Verify file was overwritten
            assert existing_file.read_text() == "new rendered content"

    def test_rendered_workflow_with_complex_path(self):
        """Test rendering workflow to a nested cache directory."""
        # Create nested output directory structure
        nested_output = self.output_dir / 'cache' / 'rendered_workflows'

        config_file = Path(self.temp_dir) / 'complex_workflow.yml'
        config_file.write_text("name: complex_workflow\nversion: 1.0")

        renderer = JinjaTemplateRenderer()

        with patch('agent_actions.tasks.services.config_renderer.render_pipeline_with_templates') as mock_render:
            mock_render.return_value = "complex workflow content"

            # Render to nested path
            renderer.render(
                config_path=str(config_file),
                template_dir=str(self.template_dir),
                output_path=str(nested_output)
            )

            # Verify nested directories were created
            assert nested_output.exists()
            assert (nested_output / 'complex_workflow.yml').exists()
            assert (nested_output / 'complex_workflow.yml').read_text() == "complex workflow content"
