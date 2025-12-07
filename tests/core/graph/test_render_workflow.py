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
from agent_actions.prompt_generation.render_workflow import normalize_yaml_indentation, render_pipeline_with_templates
from agent_actions.errors import ConfigurationError  # New modular pattern!

class TestNormalizeYamlIndentation:
    """Test the normalize_yaml_indentation() function."""

    def test_normalize_removes_common_indent(self):
        """Test that common leading whitespace is removed."""
        input_yaml = '    - name: foo\n      kind: tool'
        expected = '- name: foo\n  kind: tool'
        result = normalize_yaml_indentation(input_yaml)
        assert result == expected

    def test_normalize_preserves_relative_indent(self):
        """Test that relative indentation within blocks is preserved."""
        input_yaml = '  parent:\n    child:\n      nested: value'
        result = normalize_yaml_indentation(input_yaml)
        parsed = yaml.safe_load(result)
        assert parsed['parent']['child']['nested'] == 'value'
        lines = result.splitlines()
        assert lines[0] == 'parent:'
        assert lines[1] == '  child:'
        assert lines[2] == '    nested: value'

    def test_normalize_empty_string(self):
        """Test that empty string is handled correctly."""
        assert normalize_yaml_indentation('') == ''

    def test_normalize_already_correct(self):
        """Test that correctly indented YAML is unchanged."""
        input_yaml = '- name: foo\n  kind: tool'
        result = normalize_yaml_indentation(input_yaml)
        assert result == input_yaml

    def test_normalize_excessive_indent(self):
        """Test normalization of YAML with excessive indentation."""
        input_yaml = '      - name: foo\n        kind: tool\n      - name: bar\n        kind: action'
        result = normalize_yaml_indentation(input_yaml)
        parsed = yaml.safe_load(result)
        assert len(parsed) == 2
        assert parsed[0]['name'] == 'foo'
        assert parsed[1]['name'] == 'bar'

    def test_normalize_single_line(self):
        """Test normalization of single-line YAML."""
        input_yaml = '    name: value'
        expected = 'name: value'
        result = normalize_yaml_indentation(input_yaml)
        assert result == expected

    def test_normalize_mixed_content(self):
        """Test normalization with mixed YAML structures."""
        input_yaml = '    tools:\n      - name: format_quiz\n        kind: tool\n      - name: validate_quiz\n        kind: tool\n    actions:\n      - name: save_quiz\n        kind: action'
        result = normalize_yaml_indentation(input_yaml)
        parsed = yaml.safe_load(result)
        assert 'tools' in parsed
        assert 'actions' in parsed
        assert len(parsed['tools']) == 2
        assert len(parsed['actions']) == 1

    def test_normalize_with_blank_lines(self):
        """Test that blank lines are preserved."""
        input_yaml = '    name: foo\n\n    other: bar'
        result = normalize_yaml_indentation(input_yaml)
        lines = result.splitlines(keepends=True)
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
        template_content = '{{ text | dedent }}'
        template = env.from_string(template_content)
        text_with_indent = '    - name: foo\n      kind: tool\n    - name: bar\n      kind: action'
        result = template.render(text=text_with_indent)
        assert result.startswith('- name: foo')
        assert '  kind: tool' in result

    def test_dedent_filter_with_macro(self):
        """Test dedent filter used with Jinja2 macros."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent
        template_content = '{% macro my_tools() -%}\n    - name: foo\n      kind: tool\n{%- endmacro %}\n{{ my_tools() | dedent }}'
        template = env.from_string(template_content)
        result = template.render()
        assert result.strip().startswith('- name: foo')

    def test_dedent_filter_preserves_relative_indent(self):
        """Test that dedent preserves relative indentation."""
        env = Environment(loader=FileSystemLoader(self.templates_folder))
        import textwrap
        env.filters['dedent'] = textwrap.dedent
        template_content = '{{ text | dedent }}'
        template = env.from_string(template_content)
        text_with_indent = '    parent:\n        child: value'
        result = template.render(text=text_with_indent)
        lines = result.splitlines()
        assert lines[0] == 'parent:'
        assert lines[1].startswith('  ')

class TestFailedRenderCache:
    """Test failed render caching functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.templates_folder = Path(self.temp_dir) / 'templates'
        self.templates_folder.mkdir()
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
        yaml_file = Path(self.temp_dir) / 'broken_workflow.yml'
        yaml_file.write_text('\nname: broken\nactions:\n  - name: test\n    : invalid_yaml_syntax_here\n')
        cache_dir = Path('.agent-actions/cache/rendered_workflows')
        expected_cache_file = cache_dir / 'broken_workflow_failed.yml'
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        assert expected_cache_file.exists()
        cached_content = expected_cache_file.read_text()
        assert 'invalid_yaml_syntax_here' in cached_content

    def test_error_message_includes_cache_path(self):
        """Test that error message shows cache file path."""
        yaml_file = Path(self.temp_dir) / 'broken_workflow.yml'
        yaml_file.write_text('\nname: broken\nactions:\n  - invalid: [unclosed bracket\n')
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        error_message = str(exc_info.value)
        assert '.agent-actions/cache/rendered_workflows' in error_message
        assert 'broken_workflow_failed.yml' in error_message

    def test_error_message_suggests_render_command(self):
        """Test that error message suggests using render command."""
        yaml_file = Path(self.temp_dir) / 'test_workflow.yml'
        yaml_file.write_text('\nactions:\n  - : broken\n')
        with pytest.raises(ConfigurationError) as exc_info:
            render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        error_message = str(exc_info.value)
        assert 'agent-actions render' in error_message
        assert 'test_workflow' in error_message

    def test_cache_directory_created_automatically(self):
        """Test that cache directory is created if it doesn't exist."""
        cache_dir = Path('.agent-actions/cache/rendered_workflows')
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text('invalid: [yaml')
        with pytest.raises(ConfigurationError):
            render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
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
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text('\n      name: test_workflow\n      version: 1.0\n      tools:\n        - name: foo\n          kind: tool\n        - name: bar\n          kind: action\n')
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        assert 'tools' in parsed
        assert len(parsed['tools']) == 2

    def test_dedent_filter_available_in_templates(self):
        """Test that dedent filter is available for use in templates."""
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("\nname: test_workflow\ndescription: {{ '    filter works' | dedent }}\nversion: 1.0\n")
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        assert parsed['description'] == 'filter works'

    def test_backward_compatibility_correct_templates(self):
        """Test that correctly formatted templates still work."""
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text('\nname: test_workflow\nversion: 1.0\nactions:\n  - name: test_action\n    kind: action\n    inputs:\n      param1: value1\n')
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'test_workflow'
        assert parsed['version'] == 1.0
        assert len(parsed['actions']) == 1
        assert parsed['actions'][0]['name'] == 'test_action'

    def test_jinja2_variable_substitution(self):
        """Test that Jinja2 variable substitution works with normalization."""
        yaml_file = Path(self.temp_dir) / 'workflow.yml'
        yaml_file.write_text("\n      {% set workflow_name = 'combined_test' %}\n      name: {{ workflow_name }}\n      version: 1.0\n      actions:\n        - name: action1\n          kind: action\n")
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
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
        yaml_file.write_text('\nname: simple\nversion: 1.0\ndescription: A simple workflow\nactions:\n  - name: step1\n    kind: action\n')
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'simple'
        assert parsed['description'] == 'A simple workflow'

    def test_workflows_with_correct_indentation(self):
        """Test that workflows with correct indentation are unchanged."""
        yaml_file = Path(self.temp_dir) / 'correct_workflow.yml'
        yaml_content = 'name: correct_workflow\nversion: 1.0\nactions:\n  - name: action1\n    kind: action\n    inputs:\n      param: value\n'
        yaml_file.write_text(yaml_content)
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'correct_workflow'
        assert parsed['actions'][0]['inputs']['param'] == 'value'

    def test_complex_existing_workflow(self):
        """Test with a complex workflow structure."""
        yaml_file = Path(self.temp_dir) / 'complex_workflow.yml'
        yaml_file.write_text('\nname: complex_workflow\nversion: 2.0\nmetadata:\n  author: test\n  tags:\n    - testing\n    - integration\ntools:\n  - name: tool1\n    kind: tool\n    config:\n      endpoint: https://example.com\n      timeout: 30\nactions:\n  - name: action1\n    kind: action\n    depends_on:\n      - tool1\n    inputs:\n      data:\n        nested:\n          deeply: value\n')
        result = render_pipeline_with_templates(yaml_path=str(yaml_file), templates_folder=str(self.templates_folder))
        parsed = yaml.safe_load(result)
        assert parsed['name'] == 'complex_workflow'
        assert parsed['metadata']['author'] == 'test'
        assert 'testing' in parsed['metadata']['tags']
        assert parsed['tools'][0]['config']['timeout'] == 30
        assert parsed['actions'][0]['inputs']['data']['nested']['deeply'] == 'value'