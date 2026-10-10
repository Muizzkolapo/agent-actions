"""Outside an action's prompt, the workflow file renders at load as it always has.

Only an undefined name used other than through `is defined` or `default` now fails the
load. A guarded optional name, an include named by a variable and an import with context
load as they did, beside a prompt that renders per record.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

PROMPT = '  - name: a\n    intent: "x"\n    prompt: "Summarise {{ source.text }}"\n'


def _load(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    for name, text in (templates or {}).items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def _names(data: dict) -> list[str]:
    return [action["name"] for action in data["actions"]]


@pytest.mark.parametrize(
    "condition, kept",
    [
        pytest.param("debug is defined and debug", False, id="defined-and"),
        pytest.param("debug is not defined or not debug", True, id="not-defined-or"),
        pytest.param("enable_x | default(false)", False, id="default-filter"),
    ],
)
def test_a_guarded_optional_flag_decides_at_load(tmp_path, condition, kept):
    data = _load(
        tmp_path,
        "actions:\n" + PROMPT + f"{{% if {condition} %}}\n"
        '  - name: optional\n    intent: "y"\n    prompt: "static"\n{% endif %}\n',
    )

    assert _names(data) == (["a", "optional"] if kept else ["a"])
    assert data["actions"][0]["prompt"] == "Summarise {{ source.text }}"


@pytest.mark.parametrize(
    "setting",
    [
        pytest.param("{% set model = model | default('gpt-4o-mini') %}", id="default-of-itself"),
        pytest.param(
            "{% set model = model if model is defined else 'gpt-4o-mini' %}", id="conditional"
        ),
    ],
)
def test_a_variable_defaulted_from_an_optional_name_loads(tmp_path, setting):
    data = _load(
        tmp_path,
        setting + "\ndefaults:\n  model_name: {{ model }}\nactions:\n" + PROMPT,
    )

    assert data["defaults"]["model_name"] == "gpt-4o-mini"


def test_an_include_named_by_a_loop_variable_reads_that_variable(tmp_path):
    partial = '  - name: {name}\n    intent: "from {{{{ p }}}}"\n    prompt: "static"\n'
    data = _load(
        tmp_path,
        "actions:\n"
        + PROMPT
        + "{% for p in ['a2.j2', 'b2.j2'] %}\n{% include p %}\n{% endfor %}\n",
        templates={"a2.j2": partial.format(name="a2"), "b2.j2": partial.format(name="b2")},
    )

    assert [action["intent"] for action in data["actions"]] == ["x", "from a2.j2", "from b2.j2"]


def test_an_include_named_by_a_set_variable_reads_the_files_names(tmp_path):
    data = _load(
        tmp_path,
        "{% set part = 'defaults.j2' %}{% set model = 'm1' %}\n{% include part %}\n"
        "actions:\n" + PROMPT,
        templates={"defaults.j2": 'defaults:\n  model_name: "{{ model }}"\n'},
    )

    assert data["defaults"]["model_name"] == "m1"


@pytest.mark.parametrize(
    "importing, call",
    [
        pytest.param("{% from 'x.j2' import act with context %}", "act", id="from-import"),
        pytest.param("{% import 'x.j2' as x with context %}", "x.act", id="import-as"),
    ],
)
def test_an_import_with_context_reads_the_files_names(tmp_path, importing, call):
    data = _load(
        tmp_path,
        "{% set tone = 'formal' %}"
        + importing
        + "\nactions:\n"
        + PROMPT
        + f"  {{{{ {call}('b') | indent(2) }}}}\n",
        templates={
            "x.j2": '{% macro act(n) -%}\n- name: {{ n }}\n  intent: "{{ tone }}"\n'
            '  prompt: "In a {{ tone }} tone: {{ source.text }}"\n{%- endmacro %}\n'
        },
    )

    assert data["actions"][1]["intent"] == "formal"
    assert data["actions"][1]["prompt"] == "In a formal tone: {{ source.text }}"
