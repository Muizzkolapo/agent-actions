"""A templates/ file runs after the files it reads, and no sooner than something reads it."""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str]) -> str:
    folder = tmp_path / "templates"
    for name, text in templates.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(f'name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n')
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


BOTH_WAYS = pytest.mark.parametrize("first, second", [("a.j2", "m.j2"), ("m.j2", "a.j2")])


@BOTH_WAYS
def test_a_file_that_imports_with_context_has_set_its_names_for_a_file_that_appends(
    tmp_path, first, second
):
    templates = {
        first: "{% set items = ['x'] %}{% from 'sub/h.j2' import h with context %}\n",
        "sub/h.j2": "{% macro h() %}H{% endmacro %}\n",
        second: "{% set _ = items.append('y') %}\n",
    }

    assert _prompt(tmp_path, "{{ items | join(',') }}", templates) == "x,y"


@BOTH_WAYS
def test_a_file_that_imports_with_context_has_set_its_names_for_a_file_that_reads(
    tmp_path, first, second
):
    templates = {
        first: "{% set v = 'V' %}{% from 'sub/h.j2' import h with context %}\n",
        "sub/h.j2": "{% macro h() %}H{% endmacro %}\n",
        second: "{% set c = v ~ '!' %}\n",
    }

    assert _prompt(tmp_path, "{{ c }}", templates) == "V!"


@BOTH_WAYS
def test_a_file_included_with_context_at_a_top_level_reads_another_files_variable(
    tmp_path, first, second
):
    templates = {
        first: "{% set before = 1 %}{% include 'sub/p.j2' %}\n",
        "sub/p.j2": "P{{ v }}",
        second: "{% set v = 'V' %}\n",
    }
    workflow = f"{{% include '{first}' without context %}}"

    assert _prompt(tmp_path, workflow, templates).strip() == "PV"


@BOTH_WAYS
def test_a_list_one_file_extends_from_anothers_is_the_extended_one(tmp_path, first, second):
    templates = {
        first: "{% set items = ['x'] %}\n",
        second: "{% set items = items + ['y'] %}\n",
    }

    assert _prompt(tmp_path, "{{ items | join(',') }}", templates) == "x,y"


@pytest.mark.parametrize(
    "names",
    [("a.j2", "b.j2", "c.j2"), ("b.j2", "a.j2", "c.j2"), ("c.j2", "b.j2", "a.j2")],
    ids=["abc", "bac", "cba"],
)
def test_a_macros_parameter_is_not_a_name_its_file_sets(tmp_path, names):
    with_param, reader, setter = names
    templates = {
        with_param: "{% macro m(v) %}{% set w = v %}{{ w }}{% endmacro %}"
        "{% for v in [1] %}{% set w = v %}{% endfor %}"
        "{% set q = other | default('nq') %}\n",
        reader: "{% set w = v | default('none') %}{% set other = 'O' %}\n",
        setter: "{% set v = 'real' %}\n",
    }

    assert _prompt(tmp_path, "{{ w }}{{ q }}", templates) == "realO"


@pytest.mark.parametrize("reader", ["0.j2", "m.j2", "z.j2"])
def test_a_file_reads_the_same_one_of_two_definitions_as_the_workflow(tmp_path, reader):
    templates = {
        reader: "{% set got = n %}\n",
        "a.j2": "{% set n = 'a' %}\n",
        "b.j2": "{% set n = 'b' %}\n",
    }

    assert _prompt(tmp_path, "{{ got }}{{ n }}", templates) == "bb"


@BOTH_WAYS
def test_a_name_set_only_inside_an_if_is_found_by_a_file_that_reads_it(tmp_path, first, second):
    templates = {
        first: "{% if true %}{% set style = 'formal' %}{% endif %}\n",
        second: "{% set tone = style | upper %}\n",
    }

    assert _prompt(tmp_path, "{{ tone }}", templates) == "FORMAL"
