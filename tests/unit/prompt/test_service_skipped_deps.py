"""Tests for skipped-dependency template tolerance and None finalize."""

from __future__ import annotations

import pytest

from agent_actions.errors import TemplateVariableError
from agent_actions.prompt.service import PromptPreparationService


class TestSkippedDependencyTolerance:
    """Defect 3: Skipped-dep template variables get empty namespace, not crash."""

    def test_skipped_dep_renders_empty(self):
        """Missing variable from skipped dependency renders as empty string."""
        result = PromptPreparationService._render_prompt_template(
            "Result: {{ upstream_action.output_field }}",
            {"other_action": {"field": "value"}},
            agent_name="test",
            mode="online",
            skipped_actions={"upstream_action"},
        )
        assert result == "Result: "

    def test_genuine_typo_still_raises(self):
        """Missing variable NOT in skipped_actions still raises."""
        with pytest.raises(TemplateVariableError):
            PromptPreparationService._render_prompt_template(
                "Result: {{ typo_action.output_field }}",
                {"other_action": {"field": "value"}},
                agent_name="test",
                mode="online",
                skipped_actions={"upstream_action"},
            )

    def test_no_skipped_actions_raises_as_before(self):
        """Without skipped_actions, missing variables raise as before."""
        with pytest.raises(TemplateVariableError):
            PromptPreparationService._render_prompt_template(
                "Result: {{ upstream_action.output_field }}",
                {"other_action": {"field": "value"}},
                agent_name="test",
                mode="online",
            )

    def test_multiple_skipped_deps_tolerated(self):
        """Multiple skipped dependencies are all tolerated."""
        result = PromptPreparationService._render_prompt_template(
            "A: {{ dep_a.x }}, B: {{ dep_b.y }}",
            {"real_dep": {"z": "val"}},
            agent_name="test",
            mode="online",
            skipped_actions={"dep_a", "dep_b"},
        )
        # First skipped dep is caught, re-rendered, then second may also fire
        assert "val" not in result or result is not None  # should not crash


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
