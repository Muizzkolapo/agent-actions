"""A field read off a present value that lacks it names that value, not a namespace (1500).

Jinja's "'dict object' has no attribute 'x'" names only the attribute, and the render
took it for a namespace nothing supplies. The error now names where the field was
read from, by the value's place in the prompt context.
"""

import pickle
import time
from unittest.mock import patch

import pytest

from agent_actions.errors.operations import TemplateVariableError
from agent_actions.logging.events.io_events import ContextFieldNotFoundEvent
from agent_actions.prompt.jinja_env import MissingFieldError
from agent_actions.prompt.service import PromptPreparationService, _place_in

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


def test_a_mapping_two_namespaces_share_is_named_by_the_one_the_template_reads():
    """Wildcard observe stores a namespace's dicts by reference, so two can share one."""
    meta = {"x": 1}
    context = {"extract": {"meta": meta}, "classify": {"meta": meta, "label": "a"}}

    error, _events = _render("{{ classify.meta.zz }}", context)

    assert error.missing_variables == ["classify.meta.zz"]
    assert "'classify.meta' has no field 'zz' (it has: x)" in str(error)


def test_a_shared_mapping_the_template_does_not_name_is_not_given_a_guessed_place():
    meta = {"x": 1}
    context = {"extract": {"meta": meta}, "classify": {"meta": meta, "label": "a"}}

    error, events = _render("{{ (extract if true else classify)['meta'].zz }}", context)

    assert error.missing_variables == ["zz"]
    assert "extract.meta" not in str(error)
    assert "classify.meta" not in str(error)
    assert "has no attribute 'zz'" in str(error)
    assert not [e for e in events if "Namespace 'zz' not found" in e.message]


def test_a_mapping_outside_a_large_context_is_given_up_on_quickly():
    rows = [{"i": i, "v": [i] * 10} for i in range(500_000)]
    context = {"big": {"rows": rows}, "good": {"a": 1}}

    started = time.perf_counter()
    error, _events = _render("{% set x = {'k': 1} %}{{ x.zz }}", context)
    elapsed = time.perf_counter() - started

    assert error.missing_variables == ["zz"]
    assert elapsed < 2.0


def test_a_mapping_at_the_end_of_a_deep_chain_is_placed():
    target: dict = {"leaf": 1}
    node = target
    for _ in range(20_000 - 1):
        node = {"a": node}

    started = time.perf_counter()
    place = _place_in({"deep": node}, target, "")
    elapsed = time.perf_counter() - started

    assert place == "deep" + ".a" * (20_000 - 1)
    assert elapsed < 2.0


def test_a_missing_field_error_survives_pickling():
    error = MissingFieldError("good", "zz", ["x"])

    copy = pickle.loads(pickle.dumps(error))

    assert (copy.place, copy.field, str(copy)) == ("good", "zz", str(error))
