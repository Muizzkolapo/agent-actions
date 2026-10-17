"""A missing field named like a dict method fails as a missing field (1503).

Jinja reads `ns.items` as the dict's `items` method when the key is absent, and
`ns['items']` falls back to the same attribute, so the prompt carried
"<built-in method items of dict object ...>" and the record was sent. A call such as
`ns.items()` or `ns.get('x', 'd')` still calls the method.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors.operations import TemplateRenderingError, TemplateVariableError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService

CONTEXT = {"producer": {"label": "a", "inner": {"y": 2}}}
DICT_METHODS = [
    "items",
    "keys",
    "values",
    "get",
    "copy",
    "pop",
    "popitem",
    "update",
    "setdefault",
    "clear",
    "fromkeys",
]


def _render(template: str, context: dict | None = None) -> str:
    return PromptPreparationService._render_prompt_template(
        template, context or CONTEXT, agent_name="consumer"
    )


@pytest.mark.parametrize("name", DICT_METHODS)
@pytest.mark.parametrize(
    "form", ["{{{{ producer.{name} }}}}", "{{{{ producer['{name}'] }}}}"], ids=["dot", "subscript"]
)
def test_a_missing_field_named_like_a_dict_method_is_a_missing_field(name, form):
    with pytest.raises(TemplateVariableError) as raised:
        _render(form.format(name=name))

    assert raised.value.missing_variables == [f"producer.{name}"]
    assert f"'producer' has no field '{name}' (it has: inner, label)" in str(raised.value)


def test_a_nested_mapping_missing_an_items_field_names_its_place():
    with pytest.raises(TemplateVariableError) as raised:
        _render("{{ producer.inner.items }}")

    assert "'producer.inner' has no field 'items' (it has: y)" in str(raised.value)


@pytest.mark.parametrize(
    "template",
    [
        "{% if producer.items %}yes{% endif %}",
        "{% for x in producer.values %}{{ x }}{% endfor %}",
        "{{ producer.keys | length }}",
    ],
)
def test_a_missing_dict_method_name_is_not_truthy_or_iterable(template):
    with pytest.raises(TemplateVariableError) as raised:
        _render(template)

    assert "'producer' has no field" in str(raised.value)


def test_a_missing_dict_method_name_takes_a_default():
    assert _render("[{{ producer.items | default('none') }}]") == "[none]"
    assert _render("{{ producer.get is defined }}") == "False"


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "{% for k, v in producer.items() %}{{ k }}={{ v }};{% endfor %}",
            "label=a;inner={'y': 2};",
        ),
        ("{{ producer.keys() | list }}", "['label', 'inner']"),
        ("{{ producer.values() | list | length }}", "2"),
        ("{{ producer.get('label') }}", "a"),
        ("{{ producer.get('nope', 'fallback') }}", "fallback"),
        ("{{ producer.get('raw', producer.get('label', '')) }}", "a"),
        ("{% set c = producer.copy() %}{% set _ = c.update({'z': 1}) %}{{ c.z }}", "1"),
    ],
)
def test_a_dict_method_call_still_calls_the_method(template, expected):
    assert _render(template) == expected


def test_a_present_field_named_items_still_reads_the_field():
    assert _render("{{ producer.items }}", {"producer": {"items": ["x"]}}) == "['x']"


PROMPT = '  - name: a\n    intent: "x"\n    prompt: "Summarise {{ source.text }}"\n'


def _load(tmp_path: Path, expression: str) -> str:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(
        "{% set rec = {'a': 1} %}\n"
        f'defaults:\n  model_name: "{{{{ {expression} }}}}"\nactions:\n' + PROMPT
    )
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return str(yaml.safe_load(rendered)["defaults"]["model_name"])


@pytest.mark.parametrize("expression", ["rec.items", "rec['get']"])
def test_a_load_time_value_missing_a_dict_method_name_fails_the_load(tmp_path, expression):
    with pytest.raises(TemplateRenderingError, match="has no attribute") as raised:
        _load(tmp_path, expression)

    assert "built-in method" not in str(raised.value)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [("rec.get('a')", "1"), ("rec.get('b', 'd')", "d"), ("rec.items() | list", "[('a', 1)]")],
)
def test_a_load_time_dict_method_call_still_calls_the_method(tmp_path, expression, expected):
    assert _load(tmp_path, expression) == expected
