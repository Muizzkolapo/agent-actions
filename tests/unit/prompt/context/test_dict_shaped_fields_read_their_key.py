"""A field named items, keys or values reads its own value, not the dict method (1370).

Jinja's default `getattr` tries `getattr(obj, attribute)` before `obj[attribute]`, so dot
access on a field literally named `items`/`keys`/`values` -- a dict method name -- silently
returns the bound method instead of raising or reading the key. `_render_prompt_template`
must read the key first.
"""

from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.prompt.service import PromptPreparationService


def _render(template: str, prompt_context: dict) -> str:
    return PromptPreparationService._render_prompt_template(
        template, prompt_context, agent_name="test"
    )


def _scope_and_render(template: str, field_context: dict, context_scope: dict) -> str:
    prompt_context, _, _ = apply_context_scope(field_context, context_scope, action_name="test")
    return _render(template, prompt_context)


class TestDotAccessOnADictMethodName:
    def test_items_field_reads_its_value_not_the_method(self):
        result = _scope_and_render(
            "Items: {{ dep.items }}",
            {"dep": {"items": ["a", "b"]}},
            {"observe": ["dep.*"]},
        )
        assert result == "Items: ['a', 'b']"
        assert "built-in method" not in result

    def test_keys_field_reads_its_value_not_the_method(self):
        result = _scope_and_render(
            "Keys: {{ dep.keys }}",
            {"dep": {"keys": ["x", "y"]}},
            {"observe": ["dep.*"]},
        )
        assert result == "Keys: ['x', 'y']"
        assert "built-in method" not in result

    def test_values_field_reads_its_value_not_the_method(self):
        result = _scope_and_render(
            "Values: {{ dep.values }}",
            {"dep": {"values": [1, 2]}},
            {"observe": ["dep.*"]},
        )
        assert result == "Values: [1, 2]"
        assert "built-in method" not in result

    def test_nested_items_field_matching_the_filed_repro(self):
        result = _scope_and_render(
            "Items: {{ fetch.response.data.items }}",
            {"fetch": {"response": {"data": {"items": ["Alpha-1", "Alpha-2"]}}}},
            {"observe": ["fetch.*"]},
        )
        assert result == "Items: ['Alpha-1', 'Alpha-2']"


class TestForLoopAndLengthOverADictMethodName:
    def test_for_loop_iterates_the_items_field(self):
        result = _scope_and_render(
            "{% for item in source.items %}- {{ item.name }}: {{ item.value }}\n{% endfor %}",
            {"source": {"items": [{"name": "a", "value": 1}, {"name": "b", "value": 2}]}},
            {"observe": ["source.*"]},
        )
        assert result == "- a: 1\n- b: 2\n"

    def test_length_filter_counts_the_items_field(self):
        result = _scope_and_render(
            "Count: {{ source.items | length }}",
            {"source": {"items": ["a", "b", "c"]}},
            {"observe": ["source.*"]},
        )
        assert result == "Count: 3"


class TestOrdinaryAttributeAccessIsUnaffected:
    """A field that is not also a dict-method name keeps reading normally."""

    def test_non_colliding_field_name_still_reads(self):
        result = _scope_and_render(
            "Name: {{ dep.name }}",
            {"dep": {"name": "alice", "items": ["unused"]}},
            {"observe": ["dep.*"]},
        )
        assert result == "Name: alice"

    def test_a_missing_name_still_raises_undefined(self):
        import pytest

        from agent_actions.errors import TemplateVariableError

        with pytest.raises(TemplateVariableError):
            _scope_and_render(
                "{{ dep.not_a_real_field }}",
                {"dep": {"items": ["a"]}},
                {"observe": ["dep.items"]},
            )
