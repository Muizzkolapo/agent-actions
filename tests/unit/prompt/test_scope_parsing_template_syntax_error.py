"""Regression: extract_action_names_from_template raises on Jinja2 syntax errors.

Finding #8 (updated): scope_parsing.py:157 — TemplateSyntaxError was caught and
returned as empty set. The fix re-raises the exception so callers are forced to
handle it explicitly rather than silently receiving an empty set indistinguishable
from "template has no action references".
"""

import logging

import pytest
from jinja2.exceptions import TemplateSyntaxError

from agent_actions.prompt.context.scope_parsing import extract_action_names_from_template

_LOGGER_NAME = "agent_actions.prompt.context.scope_parsing"


class TestTemplateSyntaxErrorRaisesAndLogs:
    """TemplateSyntaxError must raise and log a warning, not return empty set."""

    def test_unclosed_block_raises_and_logs_warning(self, caplog):
        """Unclosed Jinja2 block tag raises TemplateSyntaxError and logs a warning."""
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            with pytest.raises(TemplateSyntaxError):
                extract_action_names_from_template("{% if foo %} no endif")

        assert len(caplog.records) == 1
        assert "syntax error" in caplog.records[0].message.lower()

    def test_unclosed_variable_raises_and_logs_warning(self, caplog):
        """Unclosed variable expression raises TemplateSyntaxError and logs a warning."""
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            with pytest.raises(TemplateSyntaxError):
                extract_action_names_from_template("{{ unclosed_var")

        assert len(caplog.records) == 1

    def test_warning_includes_template_snippet(self, caplog):
        """Warning message includes the template content for diagnostics."""
        template = "{% if broken %} {{ action.field }}"
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            with pytest.raises(TemplateSyntaxError):
                extract_action_names_from_template(template)

        assert len(caplog.records) == 1
        assert template[:50] in caplog.records[0].message

    def test_warning_includes_line_number(self, caplog):
        """Warning message includes the line number of the syntax error."""
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            with pytest.raises(TemplateSyntaxError):
                extract_action_names_from_template("{% if broken %}")

        assert len(caplog.records) == 1
        assert "line" in caplog.records[0].message.lower()

    def test_no_warning_on_valid_template(self, caplog):
        """Valid templates produce no warnings."""
        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            extract_action_names_from_template("{{ action.field }}")

        assert len(caplog.records) == 0


class TestValidTemplatesBehaviorUnchanged:
    """Valid templates still return correct action name sets after the fix."""

    def test_valid_template_returns_actions(self):
        """Standard template with action references returns them."""
        result = extract_action_names_from_template("{{ summarize.text }} and {{ extract.facts }}")
        assert result == {"summarize", "extract"}

    def test_empty_template_returns_empty_set(self):
        """Empty or None template returns empty set (not an error)."""
        assert extract_action_names_from_template("") == set()
        assert extract_action_names_from_template(None) == set()

    def test_template_without_actions_returns_empty_set(self):
        """Template with only special namespaces returns empty set."""
        result = extract_action_names_from_template("{{ source.text }}")
        assert result == set()

    def test_for_loop_scoped_vars_excluded(self):
        """Variables introduced by {% for %} are excluded from action names."""
        template = "{% for item in items %}{{ item.name }}{% endfor %}"
        result = extract_action_names_from_template(template)
        assert "item" not in result
