"""A file reads the same one of two definitions wherever its name falls between theirs."""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str]) -> str:
    folder = tmp_path / "templates"
    folder.mkdir()
    for name, text in templates.items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(f'name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n')
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


READER = pytest.mark.parametrize("reader", ["0_reader.j2", "m_reader.j2", "z_reader.j2"])


@READER
def test_a_macro_and_a_top_level_read_get_the_later_of_two_macros(tmp_path, reader):
    templates = {
        "a.j2": "{% macro h() %}one{% endmacro %}\n",
        "n.j2": "{% macro h() %}two{% endmacro %}\n",
        reader: "{% set intro = h() %}{% macro m() %}{{ h() }}{% endmacro %}\n",
    }

    assert _prompt(tmp_path, "{{ h() }} {{ m() }} {{ intro }}", templates) == "two two two"


@READER
def test_a_macro_alone_gets_the_later_of_two_macros(tmp_path, reader):
    templates = {
        "a.j2": "{% macro h() %}one{% endmacro %}\n",
        "n.j2": "{% macro h() %}two{% endmacro %}\n",
        reader: "{% macro m() %}{{ h() }}{% endmacro %}\n",
    }

    assert _prompt(tmp_path, "{{ m() }}", templates) == "two"


@READER
def test_a_top_level_read_gets_the_later_of_two_variables(tmp_path, reader):
    templates = {
        "a.j2": "{% set tone = 'base' %}\n",
        "n.j2": "{% set tone = 'project' %}\n",
        reader: "{% set line = 'Write in a ' ~ tone ~ ' tone.' %}\n",
    }

    assert _prompt(tmp_path, "{{ line }}", templates) == "Write in a project tone."


@pytest.mark.parametrize("reader, setter", [("a.j2", "z.j2"), ("z.j2", "a.j2")])
def test_a_file_reads_a_name_another_sets_in_a_block(tmp_path, reader, setter):
    templates = {
        reader: "{% set got = boxed | trim | upper %}\n",
        setter: "{% set boxed %} b {% endset %}\n",
    }

    assert _prompt(tmp_path, "{{ got }}", templates) == "B"
