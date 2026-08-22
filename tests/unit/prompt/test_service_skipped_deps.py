"""Tests for None finalize in prompt template rendering."""

from __future__ import annotations

import pytest

from agent_actions.errors import TemplateVariableError
from agent_actions.prompt.service import PromptPreparationService


class TestNoneFinalize:
    """P2-6: None values render as empty string, not 'None'."""

    def test_none_renders_as_empty_string(self):
        """None in prompt_context renders as empty string."""
        result = PromptPreparationService._render_prompt_template(
            "Name: {{ name }}, Phone: {{ phone }}",
            {"name": "Alice", "phone": None},
            agent_name="test",
            mode="online",
        )
        assert result == "Name: Alice, Phone: "

    def test_zero_preserved(self):
        """0 in prompt_context renders as '0', not empty."""
        result = PromptPreparationService._render_prompt_template(
            "Count: {{ count }}",
            {"count": 0},
            agent_name="test",
            mode="online",
        )
        assert result == "Count: 0"

    def test_false_preserved(self):
        """False in prompt_context renders as 'False', not empty."""
        result = PromptPreparationService._render_prompt_template(
            "Flag: {{ flag }}",
            {"flag": False},
            agent_name="test",
            mode="online",
        )
        assert result == "Flag: False"

    def test_empty_string_preserved(self):
        """Empty string in prompt_context renders as empty, not something else."""
        result = PromptPreparationService._render_prompt_template(
            "Val: {{ val }}",
            {"val": ""},
            agent_name="test",
            mode="online",
        )
        assert result == "Val: "

    def test_missing_variable_still_raises(self):
        """StrictUndefined still catches genuinely missing variables."""
        with pytest.raises(TemplateVariableError):
            PromptPreparationService._render_prompt_template(
                "{{ missing_var }}",
                {"other": "value"},
                agent_name="test",
                mode="online",
            )
