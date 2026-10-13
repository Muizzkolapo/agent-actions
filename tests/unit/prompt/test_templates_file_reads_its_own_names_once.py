"""A templates/ file's top level reads the rest of the folder's names, never its own."""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

# Unrelated files beside the one under test: how many there are must not show.
UNRELATED = pytest.mark.parametrize("unrelated", [0, 1, 2, 3])


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str], unrelated: int = 0) -> str:
    folder = tmp_path / "templates"
    folder.mkdir()
    for name, text in templates.items():
        (folder / name).write_text(text)
    for n in range(unrelated):
        (folder / f"other_{n}.j2").write_text(f"{{% set other_{n} = {n} %}}\n")
    path = tmp_path / "wf.yml"
    path.write_text(f'name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n')
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


@UNRELATED
def test_a_name_set_unless_defined_is_set(tmp_path, unrelated):
    templates = {"a.j2": "{% if flag is not defined %}{% set flag = 'on' %}{% endif %}\n"}

    assert _prompt(tmp_path, "{{ flag }}", templates, unrelated) == "on"


@UNRELATED
def test_a_count_built_on_its_own_default_counts_once(tmp_path, unrelated):
    templates = {"a.j2": "{% set n = (n | default(0)) + 1 %}\n"}

    assert _prompt(tmp_path, "{{ n }}", templates, unrelated) == "1"


@UNRELATED
def test_a_list_built_on_its_own_default_holds_one_item(tmp_path, unrelated):
    templates = {"a.j2": "{% set tags = (tags | default([])) + ['x'] %}\n"}

    assert _prompt(tmp_path, "{{ tags | join(',') }}", templates, unrelated) == "x"


@pytest.mark.parametrize("defaulting, setting", [("a.j2", "z.j2"), ("z.j2", "a.j2")])
def test_a_default_gives_way_to_the_file_that_sets_the_name(tmp_path, defaulting, setting):
    templates = {
        defaulting: "{% set style = style | default('plain') %}\n",
        setting: "{% set style = 'formal' %}\n",
    }

    assert _prompt(tmp_path, "{{ style }}", templates) == "formal"


@UNRELATED
def test_a_file_imported_by_the_workflow_ran_without_its_own_names(tmp_path, unrelated):
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "a.j2").write_text("{% set n = (n | default(0)) + 1 %}\n")
    (folder / "z.j2").write_text("{% from 'a.j2' import n %}{% set seen = n %}\n")
    for i in range(unrelated):
        (folder / f"other_{i}.j2").write_text(f"{{% set other_{i} = {i} %}}\n")
    path = tmp_path / "wf.yml"
    path.write_text(
        "{% from 'a.j2' import n as imported %}\n"
        "name: wf\nactions:\n  - name: act\n    intent: x\n"
        '    prompt: "{{ imported }} {{ seen }} {{ n }}"\n'
    )

    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )

    assert yaml.safe_load(rendered)["actions"][0]["prompt"] == "1 1 1"
