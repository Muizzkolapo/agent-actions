"""Tests for Jinja dot-access on namespaced fields in prompt templates.

Verifies that {{ action.field }} works correctly when prompt_context is built
by apply_context_scope() and rendered by _render_prompt_template().

The additive content model stores each action's output under its namespace in
field_context (e.g., field_context["write_scenario_question"] = {"question": ...}).
After apply_context_scope gates the context, Jinja templates must be able to
access these fields via dot notation: {{ write_scenario_question.question }}.
"""

import pytest

from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.prompt.service import PromptPreparationService


def _render(template: str, prompt_context: dict) -> str:
    """Render a Jinja template with the given prompt_context."""
    return PromptPreparationService._render_prompt_template(
        template, prompt_context, agent_name="test"
    )


def _scope_and_render(
    template: str,
    field_context: dict,
    context_scope: dict,
    static_data: dict | None = None,
) -> str:
    """Build prompt_context via apply_context_scope, then render the template."""
    prompt_context, _, _ = apply_context_scope(
        field_context,
        context_scope,
        static_data=static_data,
        action_name="test",
    )
    return _render(template, prompt_context)


class TestSimpleDotAccess:
    """{{ action.field }} resolves to field value from namespaced context."""

    def test_string_field(self):
        result = _scope_and_render(
            "Q: {{ dep.question }}",
            {"dep": {"question": "What is DI?", "extra": "unused"}},
            {"observe": ["dep.*"]},
        )
        assert result == "Q: What is DI?"

    def test_integer_field(self):
        result = _scope_and_render(
            "Score: {{ dep.score }}",
            {"dep": {"score": 42}},
            {"observe": ["dep.score"]},
        )
        assert result == "Score: 42"

    def test_boolean_field(self):
        result = _scope_and_render(
            "Pass: {{ dep.passed }}",
            {"dep": {"passed": True}},
            {"observe": ["dep.passed"]},
        )
        assert result == "Pass: True"

    def test_specific_field_observe(self):
        """Only the declared field is accessible when using specific (non-wildcard) observe."""
        result = _scope_and_render(
            "{{ dep.question }}",
            {"dep": {"question": "Why?", "answer": "Because."}},
            {"observe": ["dep.question"]},
        )
        assert result == "Why?"

    def test_wildcard_observe_exposes_all_fields(self):
        result = _scope_and_render(
            "{{ dep.question }} — {{ dep.answer }}",
            {"dep": {"question": "Why?", "answer": "Because."}},
            {"observe": ["dep.*"]},
        )
        assert result == "Why? — Because."


class TestForLoopAccess:
    """{% for x in action.list %} iterates over list fields."""

    def test_iterate_list_field(self):
        result = _scope_and_render(
            "{% for opt in dep.options %}{{ opt }}\n{% endfor %}",
            {"dep": {"options": ["A", "B", "C"]}},
            {"observe": ["dep.*"]},
        )
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_loop_index_with_list_field(self):
        result = _scope_and_render(
            "{% for opt in dep.options %}{{ loop.index }}. {{ opt }}\n{% endfor %}",
            {"dep": {"options": ["X", "Y"]}},
            {"observe": ["dep.options"]},
        )
        assert "1. X" in result
        assert "2. Y" in result

    def test_iterate_list_of_dicts(self):
        result = _scope_and_render(
            "{% for entry in dep.entries %}{{ entry.name }}: {{ entry.value }}\n{% endfor %}",
            {"dep": {"entries": [{"name": "a", "value": 1}, {"name": "b", "value": 2}]}},
            {"observe": ["dep.entries"]},
        )
        assert "a: 1" in result
        assert "b: 2" in result


class TestNestedDictAccess:
    """{{ action.parent.child }} accesses nested dict values."""

    def test_two_level_nesting(self):
        result = _scope_and_render(
            "Author: {{ dep.metadata.author }}",
            {"dep": {"metadata": {"author": "Alice"}}},
            {"observe": ["dep.*"]},
        )
        assert result == "Author: Alice"

    def test_three_level_nesting(self):
        result = _scope_and_render(
            "City: {{ dep.metadata.address.city }}",
            {"dep": {"metadata": {"address": {"city": "NYC"}}}},
            {"observe": ["dep.*"]},
        )
        assert result == "City: NYC"


class TestMultipleNamespaces:
    """Templates that reference fields from multiple action namespaces."""

    def test_two_namespaces(self):
        result = _scope_and_render(
            "{{ action_a.question }} — Answer: {{ action_b.answer }}",
            {
                "action_a": {"question": "What?"},
                "action_b": {"answer": "This."},
            },
            {"observe": ["action_a.question", "action_b.answer"]},
        )
        assert result == "What? — Answer: This."

    def test_wildcard_on_multiple_namespaces(self):
        result = _scope_and_render(
            "{{ source.text }} | {{ dep.summary }}",
            {
                "source": {"text": "Hello"},
                "dep": {"summary": "World"},
            },
            {"observe": ["source.*", "dep.*"]},
        )
        assert result == "Hello | World"

    def test_mixed_wildcard_and_specific(self):
        """One namespace with wildcard, another with specific field."""
        result = _scope_and_render(
            "{{ source.text }} — Score: {{ dep.score }}",
            {
                "source": {"text": "Doc", "id": "123"},
                "dep": {"score": 9, "extra": "noise"},
            },
            {"observe": ["source.*", "dep.score"]},
        )
        assert result == "Doc — Score: 9"


class TestFrameworkNamespaces:
    """Framework namespaces (seed, version, workflow) are accessible without observe."""

    def test_seed_data_accessible(self):
        result = _scope_and_render(
            "Exam: {{ seed.exam_name }} — {{ dep.question }}",
            {"dep": {"question": "What?"}},
            {"observe": ["dep.question"]},
            static_data={"exam_name": "Design Patterns"},
        )
        assert result == "Exam: Design Patterns — What?"

    def test_version_context_accessible(self):
        field_context = {
            "dep": {"f": "v"},
            "version": {"i": 3, "idx": 2, "length": 5},
        }
        result = _scope_and_render(
            "Iteration {{ version.i }} of {{ version.length }}",
            field_context,
            {"observe": ["dep.f"]},
        )
        assert result == "Iteration 3 of 5"

    def test_workflow_metadata_accessible(self):
        field_context = {
            "dep": {"f": "v"},
            "workflow": {"name": "test_workflow"},
        }
        result = _scope_and_render(
            "Workflow: {{ workflow.name }}",
            field_context,
            {"observe": ["dep.f"]},
        )
        assert result == "Workflow: test_workflow"


class TestPassthroughFieldsInTemplate:
    """Passthrough fields are accessible in Jinja templates (they stay in prompt_context)."""

    def test_passthrough_field_accessible_in_template(self):
        result = _scope_and_render(
            "ID: {{ dep.id }} — Summary: {{ dep.summary }}",
            {"dep": {"id": "doc-001", "summary": "Test"}},
            {"observe": ["dep.summary"], "passthrough": ["dep.id"]},
        )
        assert result == "ID: doc-001 — Summary: Test"


class TestDropInteraction:
    """Dropped fields are NOT accessible in Jinja templates."""

    def test_dropped_field_raises_on_access(self):
        """Accessing a dropped field raises UndefinedError."""
        from agent_actions.errors import TemplateVariableError

        with pytest.raises(TemplateVariableError):
            _scope_and_render(
                "Secret: {{ dep.api_key }}",
                {"dep": {"api_key": "secret", "name": "test"}},
                {"observe": ["dep.*"], "drop": ["dep.api_key"]},
            )

    def test_non_dropped_field_still_accessible(self):
        result = _scope_and_render(
            "Name: {{ dep.name }}",
            {"dep": {"api_key": "secret", "name": "test"}},
            {"observe": ["dep.*"], "drop": ["dep.api_key"]},
        )
        assert result == "Name: test"


class TestEdgeCases:
    """Edge cases for Jinja namespace access."""

    def test_none_value_renders(self):
        """None values render as 'None' (Jinja default behavior)."""
        result = _scope_and_render(
            "Value: {{ dep.field }}",
            {"dep": {"field": None}},
            {"observe": ["dep.field"]},
        )
        assert result == "Value: None"

    def test_empty_string_renders(self):
        result = _scope_and_render(
            "Value: '{{ dep.field }}'",
            {"dep": {"field": ""}},
            {"observe": ["dep.field"]},
        )
        assert result == "Value: ''"

    def test_zero_renders(self):
        result = _scope_and_render(
            "Count: {{ dep.count }}",
            {"dep": {"count": 0}},
            {"observe": ["dep.count"]},
        )
        assert result == "Count: 0"

    def test_empty_list_renders(self):
        result = _scope_and_render(
            "Results: {{ dep.results }}",
            {"dep": {"results": []}},
            {"observe": ["dep.results"]},
        )
        assert result == "Results: []"

    def test_undeclared_namespace_raises(self):
        """Referencing a namespace not in observe/passthrough raises."""
        from agent_actions.errors import TemplateVariableError

        with pytest.raises(TemplateVariableError):
            _scope_and_render(
                "{{ unknown_action.field }}",
                {"dep": {"field": "value"}},
                {"observe": ["dep.field"]},
            )

    def test_undeclared_field_in_namespace_raises(self):
        """Referencing a field not declared in observe (specific, not wildcard) raises."""
        from agent_actions.errors import TemplateVariableError

        with pytest.raises(TemplateVariableError):
            _scope_and_render(
                "{{ dep.undeclared }}",
                {"dep": {"question": "What?", "undeclared": "exists in data"}},
                {"observe": ["dep.question"]},
            )

    def test_conditional_on_namespace_field(self):
        """Jinja conditionals work with namespace fields."""
        template = "{% if dep.score > 5 %}HIGH{% else %}LOW{% endif %}"
        result = _scope_and_render(
            template,
            {"dep": {"score": 8}},
            {"observe": ["dep.score"]},
        )
        assert result == "HIGH"

    def test_filter_on_namespace_field(self):
        """Jinja filters work on namespace fields."""
        result = _scope_and_render(
            "{{ dep.name | upper }}",
            {"dep": {"name": "alice"}},
            {"observe": ["dep.name"]},
        )
        assert result == "ALICE"

    def test_json_serialization_in_template(self):
        """tojson filter works on namespace dict fields."""
        result = _scope_and_render(
            "{{ dep.data | tojson }}",
            {"dep": {"data": {"key": "value"}}},
            {"observe": ["dep.data"]},
        )
        assert '"key"' in result
        assert '"value"' in result
