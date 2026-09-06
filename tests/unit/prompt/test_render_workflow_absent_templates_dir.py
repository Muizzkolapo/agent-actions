"""An absent templates/ directory means the same as an empty one: no template globals."""

from pathlib import Path

import pytest

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

WORKFLOW = """\
name: wf
actions:
  - name: act
    intent: "do a thing"
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "wf.yml"
    path.write_text(WORKFLOW)
    return path


def test_renders_when_the_templates_directory_does_not_exist(tmp_path: Path, config: Path):
    rendered = render_pipeline_with_templates(
        config, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
    )

    assert "name: wf" in rendered
    assert "act" in rendered


def test_an_absent_directory_renders_the_same_as_an_empty_one(tmp_path: Path, config: Path):
    empty = tmp_path / "empty_templates"
    empty.mkdir()

    from_absent = render_pipeline_with_templates(
        config, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
    )
    from_empty = render_pipeline_with_templates(
        config, empty, compile_schemas=False, project_root=tmp_path
    )

    assert from_absent == from_empty


def test_a_templates_directory_that_exists_still_supplies_its_globals(tmp_path: Path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "macros.j2").write_text("{% set greeting = 'hello' %}")
    config = tmp_path / "wf.yml"
    config.write_text("name: {{ greeting }}\nactions: []\n")

    rendered = render_pipeline_with_templates(
        config, templates, compile_schemas=False, project_root=tmp_path
    )

    assert "hello" in rendered


def test_a_non_directory_at_the_templates_path_still_raises(tmp_path: Path, config: Path):
    not_a_dir = tmp_path / "templates"
    not_a_dir.write_text("this is a file, not a directory")

    with pytest.raises(NotADirectoryError):
        render_pipeline_with_templates(
            config, not_a_dir, compile_schemas=False, project_root=tmp_path
        )
