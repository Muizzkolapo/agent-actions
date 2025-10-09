"""
Tests for render_workflow.py - Jinja2 template rendering and YAML normalization.

This module tests:
1. normalize_yaml_indentation() function
2. dedent Jinja2 filter
3. Failed render caching
4. Integration with template rendering
5. Backward compatibility
"""

import pytest
import yaml
import tempfile
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from agent_actions.core.graph.render_workflow import (
    normalize_yaml_indentation,
    render_pipeline_with_templates
)
from agent_actions.core.exceptions import ConfigurationError


class TestNormalizeYamlIndentation:
    """Test the normalize_yaml_indentation() function."""

    def test_normalize_removes_common_indent(self):
        """Test that common leading whitespace is removed."""
        input_yaml = "    - name: foo\n      kind: tool"
        expected = "- name: foo\n  kind: tool"
        result = normalize_yaml_indentation(input_yaml)
        assert result == expected

    def test_normalize_preserves_relative_indent(self):
        """Test that relative indentation within blocks is preserved."""
        input_yaml = "  parent:\n    child:\n      nested: value"
        result = normalize_yaml_indentation(input_yaml)

        # Parse to ensure structure is valid
        parsed = yaml.safe_load(result)
        assert parsed['parent']['child']['nested'] == 'value'

        # Verify structure is correct - relative indentation preserved
        lines = result.splitlines()
        assert lines[0] == 'parent:'
        assert lines[1] == '  child:'
        assert lines[2] == '    nested: value'

    def test_normalize_empty_string(self):
        """Test that empty string is handled correctly."""
        assert normalize_yaml_indentation("") == ""

    def test_normalize_already_correct(self):
        """Test that correctly indented YAML is unchanged."""
        input_yaml = "- name: foo\n  kind: tool"
        result = normalize_yaml_indentation(input_yaml)
        assert result == input_yaml

    def test_normalize_excessive_indent(self):
        """Test normalization of YAML with excessive indentation."""
        input_yaml = "      - name: foo\n        kind: tool\n      - name: bar\n        kind: action"
        result = normalize_yaml_indentation(input_yaml)

        # Should parse successfully after normalization
        parsed = yaml.safe_load(result)
        assert len(parsed) == 2
        assert parsed[0]['name'] == 'foo'
        assert parsed[1]['name'] == 'bar'

    def test_normalize_single_line(self):
        """Test normalization of single-line YAML."""
        input_yaml = "    name: value"
        expected = "name: value"
        result = normalize_yaml_indentation(input_yaml)
        assert result == expected

    def test_normalize_mixed_content(self):
        """Test normalization with mixed YAML structures."""
        input_yaml = """    tools:
      - name: format_quiz
        kind: tool
      - name: validate_quiz
        kind: tool
    actions:
      - name: save_quiz
        kind: action"""

        result = normalize_yaml_indentation(input_yaml)
        parsed = yaml.safe_load(result)

        assert 'tools' in parsed
        assert 'actions' in parsed
        assert len(parsed['tools']) == 2
        assert len(parsed['actions']) == 1

    def test_normalize_with_blank_lines(self):
        """Test that blank lines are preserved."""
        input_yaml = "    name: foo\n\n    other: bar"
        result = normalize_yaml_indentation(input_yaml)
        lines = result.splitlines(keepends=True)

        # Should still have blank line
        assert len([l for l in lines if l.strip() == '']) > 0


class TestDedentFilter:
    """Test the dedent Jinja2 filter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / 'templates'
        self.templates_folder.mkdir()

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_dedent_filter_available(self):
        """Test that dedent filter is registered in Environment."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))

        # Register filter as render_workflow does
        import textwrap
        env.filters['dedent'] = textwrap.dedent

        assert 'dedent' in env.filters
        assert env.filters['dedent'] == textwrap.dedent

    def test_dedent_filter_strips_indent(self):
        """Test that dedent filter strips leading whitespace."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent

        template_content = "{{ '    - name: foo' | dedent }}"
        template = env.from_string(template_content)
        result = template.render()

        assert result == '- name: foo'

    def test_dedent_filter_with_multiline(self):
        """Test dedent filter with multi-line strings."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent

        template_content = """{{ text | dedent }}"""
        template = env.from_string(template_content)

        text_with_indent = """    - name: foo
      kind: tool
    - name: bar
      kind: action"""

        result = template.render(text=text_with_indent)

        # Should remove common leading whitespace
        assert result.startswith('- name: foo')
        assert '  kind: tool' in result

    def test_dedent_filter_with_macro(self):
        """Test dedent filter used with Jinja2 macros."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent

        template_content = """{% macro my_tools() -%}
    - name: foo
      kind: tool
{%- endmacro %}
{{ my_tools() | dedent }}"""

        template = env.from_string(template_content)
        result = template.render()

        # Should strip the leading spaces from macro output
        assert result.strip().startswith('- name: foo')

    def test_dedent_filter_preserves_relative_indent(self):
        """Test that dedent preserves relative indentation."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent

        template_content = """{{ text | dedent }}"""
        template = env.from_string(template_content)

        text_with_indent = """    parent:
        child: value"""

        result = template.render(text=text_with_indent)

        # Should remove common indent but preserve relative
        lines = result.splitlines()
        assert lines[0] == 'parent:'
        assert lines[1].startswith('  ')  # Relative indent preserved


class TestFailedRenderCache:
    """Test failed render caching functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / 'templates'
        self.templates_folder.mkdir()

        # Change to temp directory for cache tests
        self.original_cwd = Path.cwd()
        import os
        os.chdir(self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        import os
        os.chdir(self.original_cwd)
        shutil.rmtree(self.temp_dir)

    def test_failed_render_saved_to_cache(self):
        """Test that failed YAML renders are saved to cache."""
        # Create a template that renders to invalid YAML
        # (even after normalization)
        yaml_file = Path(self.temp_dir) / 'broken_workflow.yml'
        yaml_file.write_text("""
name: broken
actions:
  - name: test
    : invalid_yaml_syntax_here
""")

        cache_dir = Path('.agent-actions/cache/rendered_workflows')
        expected_cache_file = cache_dir / 'broken_workflow_failed.yml'

        # Render should fail with ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder)
            )

        # Verify cache file was created
        assert expected_cache_file.exists()

        # Verify cache contains rendered content
        cached_content = expected_cache_file.read_text()
        assert 'invalid_yaml_syntax_here' in cached_content

    def test_error_message_includes_cache_path(self):
        """Test that error message shows cache file path."""
        yaml_file = Path(self.temp_dir) / 'broken_workflow.yml'
        yaml_file.write_text("""
name: broken
actions:
  - invalid: [unclosed bracket
""")

        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder)
            )

        error_message = str(exc_info.value)

        # Error should mention cache location
        assert '.agent-actions/cache/rendered_workflows' in error_message
        assert 'broken_workflow_failed.yml' in error_message

    def test_error_message_suggests_render_command(self):
        """Test that error message suggests using render command."""
        yaml_file = Path(self.temp_dir) / 'test_workflow.yml'
        yaml_file.write_text("""
actions:
  - : broken
""")

        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder)
            )

        error_message = str(exc_info.value)

        # Should suggest render command
        assert 'agent-actions render' in error_message
        assert 'test_workflow' in error_message

    def test_cache_directory_created_automatically(self):
        """Test that cache directory is created if it doesn't exist."""
        cache_dir = Path('.agent-actions/cache/rendered_workflows')

        # Ensure cache doesn't exist
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("invalid: [yaml")

        with pytest.raises(ConfigurationError):
            render_pipeline_with_templates(
                yaml_path=str(yaml_file),
                templates_folder=str(self.templates_folder)
            )

        # Cache directory should now exist
        assert cache_dir.exists()
        assert cache_dir.is_dir()


class TestRenderPipelineIntegration:
    """Integration tests for render_pipeline_with_templates."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / 'templates'
        self.templates_folder.mkdir()

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_excessive_indent_workflow_normalized(self):
        """Test that workflows with excessive indent are auto-normalized."""
        # Create a workflow with excessive indentation (simulates macro output)
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("""
      name: test_workflow
      version: 1.0
      tools:
        - name: foo
          kind: tool
        - name: bar
          kind: action
""")

        # Should render successfully due to normalization
        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        # Verify it parses as valid YAML
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        assert 'tools' in parsed
        assert len(parsed['tools']) == 2

    def test_dedent_filter_available_in_templates(self):
        """Test that dedent filter is available for use in templates."""
        # Use dedent filter on a string variable
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("""
name: test_workflow
description: {{ '    filter works' | dedent }}
version: 1.0
""")

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        # Should render and parse successfully
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        # dedent removes leading spaces, so '    filter works' becomes 'filter works'
        assert parsed['description'] == 'filter works'

    def test_backward_compatibility_correct_templates(self):
        """Test that correctly formatted templates still work."""
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("""
name: test_workflow
version: 1.0
actions:
  - name: test_action
    kind: action
    inputs:
      param1: value1
""")

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        assert parsed['version'] == 1.0
        assert len(parsed['actions']) == 1
        assert parsed['actions'][0]['name'] == 'test_action'

    def test_jinja2_variable_substitution(self):
        """Test that Jinja2 variable substitution works with normalization."""
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("""
      {% set workflow_name = 'combined_test' %}
      name: {{ workflow_name }}
      version: 1.0
      actions:
        - name: action1
          kind: action
""")

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'combined_test'
        assert 'actions' in parsed
        assert len(parsed['actions']) == 1


class TestBackwardCompatibility:
    """Test backward compatibility with existing workflows."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / 'templates'
        self.templates_folder.mkdir()

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def test_workflows_without_templates(self):
        """Test that workflows without templates still work."""
        yaml_file = Path(self.temp_dir) / 'simple_workflow.yml'
        yaml_file.write_text("""
name: simple
version: 1.0
description: A simple workflow
actions:
  - name: step1
    kind: action
""")

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'simple'
        assert parsed['description'] == 'A simple workflow'

    def test_workflows_with_correct_indentation(self):
        """Test that workflows with correct indentation are unchanged."""
        yaml_file = Path(self.temp_dir) / 'correct_workflow.yml'
        yaml_content = """name: correct_workflow
version: 1.0
actions:
  - name: action1
    kind: action
    inputs:
      param: value
"""
        yaml_file.write_text(yaml_content)

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        # Should parse correctly
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'correct_workflow'
        assert parsed['actions'][0]['inputs']['param'] == 'value'

    def test_complex_existing_workflow(self):
        """Test with a complex workflow structure."""
        yaml_file = Path(self.temp_dir) / 'complex_workflow.yml'
        yaml_file.write_text("""
name: complex_workflow
version: 2.0
metadata:
  author: test
  tags:
    - testing
    - integration
tools:
  - name: tool1
    kind: tool
    config:
      endpoint: https://example.com
      timeout: 30
actions:
  - name: action1
    kind: action
    depends_on:
      - tool1
    inputs:
      data:
        nested:
          deeply: value
""")

        result = render_pipeline_with_templates(
            yaml_path=str(yaml_file),
            templates_folder=str(self.templates_folder)
        )

        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'complex_workflow'
        assert parsed['metadata']['author'] == 'test'
        assert 'testing' in parsed['metadata']['tags']
        assert parsed['tools'][0]['config']['timeout'] == 30
        assert parsed['actions'][0]['inputs']['data']['nested']['deeply'] == 'value'
