"""A field read off a present value that lacks it names that value, not a namespace (1500).

Jinja's "'dict object' has no attribute 'x'" names only the attribute, and the render
took it for a namespace nothing supplies. The error now names where the field was
read from, by the value's place in the prompt context.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.logging.events.io_events import ContextFieldNotFoundEvent
from agent_actions.prompt.service import PromptPreparationService

CONTEXT = {
    "good": {"x": 1, "inner": {"y": 2}, "items": [{"title": "a"}, {"name": "b"}]},
    "other": {"z": 3},
}


def _render(template: str, context: dict | None = None):
    events: list = []
    with (
        patch("agent_actions.prompt.service.fire_event", side_effect=events.append),
        pytest.raises(TemplateVariableError) as raised,
    ):
        PromptPreparationService._render_prompt_template(
            template, context or CONTEXT, agent_name="consumer"
        )
    field_events = [e for e in events if isinstance(e, ContextFieldNotFoundEvent)]
    return raised.value, field_events


@pytest.mark.parametrize(
    "template",
    [
        "{{ good.missing_field }}",
        "{{ good['missing_field'] }}",
        "{% if good.missing_field %}yes{% endif %}",
    ],
)
def test_a_field_the_namespace_lacks_is_named_with_its_namespace(template):
    error, events = _render(template)

    assert error.missing_variables == ["good.missing_field"]
    assert "'good' has no field 'missing_field' (it has: inner, items, x)" in str(error)
    (event,) = events
    assert event.namespace == "good"
    assert "Namespace 'missing_field' not found" not in event.message
    assert "Field 'missing_field' not found in 'good'" in event.message


def test_a_field_a_nested_mapping_lacks_is_named_with_its_path():
    error, _events = _render("{{ good.inner.nope }}")

    assert error.missing_variables == ["good.inner.nope"]
    assert "'good.inner' has no field 'nope' (it has: y)" in str(error)


def test_a_field_a_list_member_lacks_is_named_with_its_place():
    error, _events = _render("{% for item in good['items'] %}{{ item.title }}{% endfor %}")

    assert error.missing_variables == ["good.items[1].title"]
    assert "'good.items[1]' has no field 'title' (it has: name)" in str(error)


def test_a_field_of_a_value_the_template_built_is_not_called_a_namespace():
    error, events = _render("{% set local = {'a': 1} %}{{ local.b }}")

    assert error.missing_variables == ["b"]
    assert not [e for e in events if "Namespace 'b' not found" in e.message]


def test_a_missing_field_with_a_default_still_renders():
    rendered = PromptPreparationService._render_prompt_template(
        "[{{ good.missing_field | default('none') }}]", CONTEXT, agent_name="consumer"
    )

    assert rendered == "[none]"


def test_a_namespace_nothing_supplies_is_still_reported_as_one():
    _error, events = _render("{{ nowhere }}")

    (event,) = events
    assert "Namespace 'nowhere' not found in context" in event.message
