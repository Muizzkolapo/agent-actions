"""A templates/ file imported or included with context reads its importer's names, then the folder's."""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _actions(tmp_path: Path, workflow: str, templates: dict[str, str]) -> list[dict]:
    folder = tmp_path / "templates"
    for name, text in templates.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"]


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str]) -> str:
    workflow = f'name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n'
    return _actions(tmp_path, workflow, templates)[0]["prompt"]


DEFINER = pytest.mark.parametrize("definer", ["a_d.j2", "z_d.j2"])


@DEFINER
def test_a_prompt_in_a_file_imported_with_context_renders_a_later_files_variable(tmp_path, definer):
    templates = {
        "m_r.j2": "{% set mine = 1 %}{% import 'lib/b.j2' as b with context %}"
        "{% macro act(n) %}{{ b.act(n) }}{% endmacro %}\n",
        "lib/b.j2": "{% macro act(n) %}\n- name: {{ n }}\n  intent: x\n"
        '  prompt: "Do {{ source.text }} in {{ style }}"\n{% endmacro %}\n',
        definer: "{% set style = 'formal' %}\n",
    }
    workflow = "name: wf\nactions:\n  {{ act('summarize') | indent(2) }}\n"

    actions = _actions(tmp_path, workflow, templates)

    assert actions[0]["prompt"] == "Do {{ source.text }} in formal"


@DEFINER
def test_a_scoped_block_in_a_file_included_with_context_reads_a_later_files_variable(
    tmp_path, definer
):
    templates = {
        "m_r.j2": "{% set mine = 1 %}{% macro show() %}{% include 'lib/p.j2' %}{% endmacro %}\n",
        "lib/p.j2": "{% set own = 1 %}{{ mine }}{% block b scoped %}{{ style }}{% endblock %}{{ own }}",
        definer: "{% set style = 'formal' %}\n",
    }

    assert _prompt(tmp_path, "{{ show() }}", templates) == "1formal1"


@pytest.mark.parametrize("before_import", ["", "{% set mine = 1 %}"], ids=["bare", "after-a-set"])
def test_a_file_imported_with_context_calls_the_definition_that_ran_later(tmp_path, before_import):
    templates = {
        "a_d.j2": "{% macro same() %}D{% endmacro %}\n",
        "m_r.j2": before_import + "{% import 'lib/b.j2' as b with context %}"
        "{% macro show() %}{{ b.rd() }}{% endmacro %}\n",
        "lib/b.j2": "{% macro rd() %}{{ same() }}{% endmacro %}\n",
        "z_n.j2": "{% macro same() %}N{% endmacro %}\n",
    }

    assert _prompt(tmp_path, "{{ show() }}|{{ same() }}", templates) == "N|N"


@DEFINER
@pytest.mark.parametrize(
    "importing",
    [
        "{% from 'lib/b.j2' import h with context %}",
        "{% for n in [1] %}{% from 'lib/b.j2' import h with context %}"
        "{% set out.h = h %}{% endfor %}{% set h = out.h %}",
    ],
    ids=["top-level", "in-a-loop"],
)
def test_a_file_imported_with_context_reads_its_importers_name_before_the_folders(
    tmp_path, definer, importing
):
    templates = {
        "m_r.j2": "{% set out = namespace(h=none) %}{% set style = 'mine' %}"
        + importing
        + "{% macro show() %}{{ h() }}{% endmacro %}\n",
        "lib/b.j2": "{% set seen = style %}{% macro h() %}{{ seen }}{% endmacro %}\n",
        definer: "{% set style = 'formal' %}{% set other = 1 %}\n",
        "n_reads.j2": "{% set got = other %}\n",
    }

    assert _prompt(tmp_path, "{{ show() }}", templates) == "mine"


@pytest.mark.parametrize("reader, setter", [("a.j2", "z.j2"), ("z.j2", "a.j2")])
def test_a_file_reads_names_another_sets_by_unpacking_and_in_a_block(tmp_path, reader, setter):
    templates = {
        reader: "{% set got = first ~ second ~ (boxed | trim) %}\n",
        setter: "{% set first, second = 'f', 's' %}{% set boxed %} b {% endset %}\n",
    }

    assert _prompt(tmp_path, "{{ got }}", templates) == "fsb"
