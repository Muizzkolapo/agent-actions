"""Tests for Jinja2 inline code escaping.

Verifies that escape_jinja_in_inline_code correctly wraps Jinja syntax
inside markdown inline code spans with {% raw %} while leaving real
Jinja2 constructs and fenced code blocks untouched.
"""

import pytest
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

from agent_actions.utils.template_escape import escape_jinja_in_inline_code


class TestEscapeJinjaInInlineCode:
    """Unit tests for the escape function itself."""

    def test_single_backtick_block_tag(self):
        result = escape_jinja_in_inline_code("Use `{% test %}` here")
        assert result == "Use `{% raw %}{% test %}{% endraw %}` here"

    def test_single_backtick_variable(self):
        result = escape_jinja_in_inline_code('Use `{{ ref("model") }}` in dbt')
        assert result == 'Use `{% raw %}{{ ref("model") }}{% endraw %}` in dbt'

    def test_double_backtick(self):
        result = escape_jinja_in_inline_code("Use ``{% test %}`` here")
        assert result == "Use ``{% raw %}{% test %}{% endraw %}`` here"

    def test_multiple_inline_spans(self):
        line = "`{% test %}` to `{% macro %}`"
        result = escape_jinja_in_inline_code(line)
        assert "{% raw %}{% test %}{% endraw %}" in result
        assert "{% raw %}{% macro %}{% endraw %}" in result

    def test_real_jinja_untouched(self):
        template = "{% for x in items %}{{ x }}{% endfor %}"
        assert escape_jinja_in_inline_code(template) == template

    def test_mixed_real_and_inline(self):
        template = "Use `{% test %}` like this: {% for x in items %}{{ x }}{% endfor %}"
        result = escape_jinja_in_inline_code(template)
        assert "{% raw %}{% test %}{% endraw %}" in result
        assert "{% for x in items %}" in result
        assert "{% endfor %}" in result

    def test_fenced_code_block_not_escaped(self):
        template = "```\n{% test %}\n```"
        result = escape_jinja_in_inline_code(template)
        assert "{% raw %}" not in result

    def test_fenced_code_block_with_lang_not_escaped(self):
        template = "```sql\n{% test %}\n```"
        result = escape_jinja_in_inline_code(template)
        assert "{% raw %}" not in result

    def test_plain_text_unchanged(self):
        text = "Just plain text with no special characters"
        assert escape_jinja_in_inline_code(text) == text

    def test_inline_code_without_jinja_unchanged(self):
        text = "Use `print('hello')` to debug"
        assert escape_jinja_in_inline_code(text) == text

    def test_empty_string(self):
        assert escape_jinja_in_inline_code("") == ""

    def test_no_braces_fast_path(self):
        """Templates without { skip regex entirely."""
        text = "No braces here at all"
        assert escape_jinja_in_inline_code(text) == text

    def test_actual_failing_line(self):
        """The exact line from code_options_quiz.md that caused the bug."""
        line = (
            "- Must be syntactically valid \u2014 if you change an opening block tag "
            "(e.g. `{% test %}` to `{% macro %}`), update the closing tag to match "
            "(e.g. `{% endtest %}` to `{% endmacro %}`)"
        )
        result = escape_jinja_in_inline_code(line)
        assert "{% raw %}{% test %}{% endraw %}" in result
        assert "{% raw %}{% macro %}{% endraw %}" in result
        assert "{% raw %}{% endtest %}{% endraw %}" in result
        assert "{% raw %}{% endmacro %}{% endraw %}" in result


class TestRenderIntegration:
    """Integration tests: escape + Jinja2 rendering end-to-end."""

    @pytest.fixture()
    def jinja_env(self):
        return Environment(
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def test_inline_code_survives_rendering(self, jinja_env):
        """Literal {% test %} in backticks renders as literal text."""
        template = "Use `{% test %}` in your code\n{% for x in items %}- {{ x }}\n{% endfor %}"
        escaped = escape_jinja_in_inline_code(template)
        rendered = jinja_env.from_string(escaped).render(items=["a", "b"])
        assert "{% test %}" in rendered
        assert "- a" in rendered
        assert "- b" in rendered
        assert "{% raw %}" not in rendered

    def test_inline_variable_survives_rendering(self, jinja_env):
        """Literal {{ ref() }} in backticks renders as literal text."""
        template = 'Use `{{ ref("model") }}` for references. Value: {{ value }}'
        escaped = escape_jinja_in_inline_code(template)
        rendered = jinja_env.from_string(escaped).render(value="hello")
        assert '{{ ref("model") }}' in rendered
        assert "Value: hello" in rendered

    def test_without_escape_raises(self, jinja_env):
        """Confirm that without escaping, the template fails."""
        template = "Use `{% test %}` in your code"
        with pytest.raises(TemplateSyntaxError):
            jinja_env.from_string(template)

    def test_full_prompt_template_pattern(self, jinja_env):
        """Simulates the real-world pattern: rules with code examples + seed data loop."""
        template = """## RULES
- Copy the code EXACTLY
- Must be syntactically valid \u2014 if you change `{% test %}` to `{% macro %}`, update the closing tag
- No inline comments

## PATTERNS
{% for p in seed_patterns %}
- {{ p }}
{% endfor %}"""
        escaped = escape_jinja_in_inline_code(template)
        rendered = jinja_env.from_string(escaped).render(seed_patterns=["pattern_a", "pattern_b"])
        assert "{% test %}" in rendered
        assert "{% macro %}" in rendered
        assert "- pattern_a" in rendered
        assert "- pattern_b" in rendered

    def test_fenced_block_with_real_jinja_renders(self, jinja_env):
        """Fenced code blocks with real Jinja must still render."""
        template = "```\n{{ code_output }}\n```"
        escaped = escape_jinja_in_inline_code(template)
        rendered = jinja_env.from_string(escaped).render(code_output="print('hi')")
        assert "print('hi')" in rendered

    def test_known_tag_in_inline_code(self, jinja_env):
        """Known Jinja tags (macro, for) in inline code are also escaped."""
        template = "Use `{% for x in y %}` syntax. {% for i in items %}{{ i }}{% endfor %}"
        escaped = escape_jinja_in_inline_code(template)
        rendered = jinja_env.from_string(escaped).render(items=["a"])
        assert "{% for x in y %}" in rendered
        assert "a" in rendered
