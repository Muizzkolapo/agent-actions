"""An include without context yields its text wherever it is written."""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str], head: str = "") -> str:
    folder = tmp_path / "templates"
    for name, text in templates.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(
        f'{head}name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n'
    )
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


PARTIAL = pytest.mark.parametrize("partial", ["sub/p.j2", "p2.jinja2"])


@PARTIAL
def test_in_a_macro_of_a_templates_file(tmp_path, partial):
    templates = {
        "a.j2": "{% macro framed() %}[{% include '"
        + partial
        + "' without context %}]{% endmacro %}\n",
        partial: "P fixed",
    }

    assert _prompt(tmp_path, "{{ framed() }}", templates) == "[P fixed]"


@PARTIAL
def test_in_a_set_block_of_a_templates_file(tmp_path, partial):
    templates = {
        "a.j2": "{% set line %}<{% include '" + partial + "' without context %}>{% endset %}\n",
        partial: "P fixed",
    }

    assert _prompt(tmp_path, "{{ line }}", templates) == "<P fixed>"


def test_in_a_macro_and_a_set_block_of_the_workflow_file(tmp_path):
    head = (
        "{% macro framed() %}[{% include 'p.j2' without context %}]{% endmacro %}\n"
        "{% set line %}<{% include 'p.j2' without context %}>{% endset %}\n"
    )

    prompt = _prompt(tmp_path, "{{ framed() }} {{ line }}", {"p.j2": "P fixed"}, head=head)

    assert prompt == "[P fixed] <P fixed>"


def test_in_a_call_body_and_a_filter_block(tmp_path):
    templates = {
        "a.j2": "{% macro wrap() %}({{ caller() }}){% endmacro %}"
        "{% macro both() %}"
        "{% call wrap() %}{% include 'p.j2' without context %}{% endcall %}"
        "{% filter upper %}{% include 'p.j2' without context %}{% endfilter %}"
        "{% endmacro %}\n",
        "p.j2": "p fixed",
    }

    assert _prompt(tmp_path, "{{ both() }}", templates) == "(p fixed)P FIXED"


def test_in_a_macro_it_reads_another_files_variable_and_not_the_macros_argument(tmp_path):
    templates = {
        "a.j2": "{% macro framed(tone) %}[{% include 'p.j2' without context %}]{% endmacro %}\n",
        "p.j2": "P {{ style }}{{ tone | default('') }}",
        "z.j2": "{% set style = 'formal' %}\n",
    }

    assert _prompt(tmp_path, "{{ framed('loud') }}", templates) == "[P formal]"


def test_a_missing_file_ignored_in_a_macro_yields_nothing_and_named_fails(tmp_path):
    templates = {
        "a.j2": "{% macro soft() %}[{% include 'none.j2' ignore missing without context %}]{% endmacro %}"
        "{% macro hard() %}[{% include 'none.j2' without context %}]{% endmacro %}\n",
    }

    assert _prompt(tmp_path, "{{ soft() }}", templates) == "[]"
    (tmp_path / "wf.yml").unlink()
    with pytest.raises(TemplateRenderingError, match="none.j2"):
        _prompt(tmp_path, "{{ hard() }}", {})


def test_at_a_top_level_and_with_context_as_before(tmp_path):
    templates = {
        "a.j2": "{% macro framed(tone) %}[{% include 'p.j2' %}]{% endmacro %}\n",
        "p.j2": "P{{ tone | default('') }}",
    }

    prompt = _prompt(
        tmp_path, "{{ framed(' loud') }} {% include 'p.j2' without context %}", templates
    )

    assert prompt == "[P loud] P"
