"""Tests for the template variable validator."""

import pytest

from agent_actions.validation.preflight import TemplateVariableValidator


class TestTemplateVariableValidator:
    """Tests for TemplateVariableValidator class."""

    def test_validates_simple_template(self):
        """Test validation of simple template with available variables."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {"template": "Hello {{ name }}", "context": {"name": "World"}},
            {"agent_name": "test"},
        )
        assert result is True
        assert not validator.has_errors()

    def test_detects_missing_variable(self):
        """Test detection of missing template variable."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {"template": "{{ name }} {{ missing }}", "context": {"name": "test"}},
            {"agent_name": "test", "strict": True},
        )
        assert result is False
        assert validator.has_errors()
        assert any("missing" in err.lower() for err in validator.get_errors())

    def test_handles_nested_variables(self):
        """Test handling of nested variable access."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {
                "template": "{{ user.name }}",
                "context": {"user": {"name": "Alice"}},
            },
            {"agent_name": "test"},
        )
        assert result is True

    def test_handles_template_syntax_error(self):
        """Test handling of invalid Jinja2 syntax."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {"template": "{{ unclosed", "context": {}},
            {"agent_name": "test"},
        )
        assert result is False
        assert validator.has_errors()

    def test_returns_available_variables_in_error(self):
        """Test that errors include available variables."""
        validator = TemplateVariableValidator()
        validator.validate(
            {"template": "{{ missing }}", "context": {"available1": 1, "available2": 2}},
            {"agent_name": "test", "strict": True},
        )
        issues = validator.get_issues()
        assert len(issues) > 0
        # Available refs should be included
        assert "available1" in issues[0].available_refs or "available2" in issues[0].available_refs

    def test_validate_template_string_convenience_method(self):
        """Test the convenience method for validating template strings."""
        validator = TemplateVariableValidator()
        is_valid, missing, available = validator.validate_template_string(
            template="{{ a }} {{ b }}",
            context={"a": 1},
            agent_name="test",
        )
        assert not is_valid
        assert "b" in missing
        assert "a" in available

    def test_empty_template(self):
        """Test validation with empty template."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {"template": "", "context": {"a": 1}},
            {"agent_name": "test"},
        )
        assert result is True

    def test_template_with_only_literals(self):
        """Test template with no variables."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {"template": "Hello World", "context": {}},
            {"agent_name": "test"},
        )
        assert result is True

    def test_ignores_jinja_builtins(self):
        """Test that Jinja2 builtin functions are ignored."""
        validator = TemplateVariableValidator()
        result = validator.validate(
            {
                "template": "{% for i in range(5) %}{{ i }}{% endfor %}",
                "context": {},
            },
            {"agent_name": "test", "ignore_builtins": True},
        )
        # range is a builtin, should not be flagged as missing
        assert result is True
