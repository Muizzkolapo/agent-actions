"""A templates/ file contributes the names it exports, and nothing Jinja adds of its own.

``template.module`` carries ``__name__`` and ``_body_stream`` alongside the file's
exported names, so registering its whole ``vars()`` made every file after the first
collide with the previous one on names no file defines.
"""

import logging
from pathlib import Path

import pytest

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

_LOGGER_NAME = "agent_actions.prompt.render_workflow"

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


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    folder = tmp_path / "templates"
    folder.mkdir()
    return folder


def _redefinition_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == _LOGGER_NAME and "redefines global name" in r.getMessage()
    ]


def test_two_files_sharing_no_names_load_without_a_warning(
    tmp_path: Path, config: Path, templates: Path, caplog: pytest.LogCaptureFixture
):
    (templates / "p.j2").write_text("Write in a {{ house_style }} tone.\n")
    (templates / "prompts.j2").write_text("{% set house_style = 'formal' %}\n")

    with caplog.at_level(logging.WARNING):
        render_pipeline_with_templates(
            config, templates, compile_schemas=False, project_root=tmp_path
        )

    assert _redefinition_warnings(caplog) == []


def test_two_files_defining_the_same_macro_warn_naming_only_that_macro(
    tmp_path: Path, config: Path, templates: Path, caplog: pytest.LogCaptureFixture
):
    (templates / "prompts.j2").write_text("{% macro house_length() %}y{% endmacro %}\n")
    (templates / "helpers.j2").write_text("{% macro house_length() %}z{% endmacro %}\n")

    with caplog.at_level(logging.WARNING):
        render_pipeline_with_templates(
            config, templates, compile_schemas=False, project_root=tmp_path
        )

    warnings = _redefinition_warnings(caplog)
    assert len(warnings) == 1
    assert "house_length" in warnings[0]
    assert "__name__" not in warnings[0]
    assert "_body_stream" not in warnings[0]


def test_one_collision_among_three_files_is_reported_alone(
    tmp_path: Path, config: Path, templates: Path, caplog: pytest.LogCaptureFixture
):
    (templates / "common.j2").write_text("{% macro std_action() %}x{% endmacro %}\n")
    (templates / "prompts.j2").write_text("{% macro house_length() %}y{% endmacro %}\n")
    (templates / "helpers.j2").write_text("{% macro house_length() %}z{% endmacro %}\n")

    with caplog.at_level(logging.WARNING):
        render_pipeline_with_templates(
            config, templates, compile_schemas=False, project_root=tmp_path
        )

    warnings = _redefinition_warnings(caplog)
    assert len(warnings) == 1
    assert "house_length" in warnings[0]
    assert "std_action" not in warnings[0]


def test_jinja_module_internals_do_not_become_workflow_globals(tmp_path: Path, templates: Path):
    (templates / "a.j2").write_text("{% set tone = 'formal' %}\n")
    (templates / "b.j2").write_text("{% macro m() %}x{% endmacro %}\n")
    config = tmp_path / "wf.yml"
    config.write_text(
        'name: wf\ndescription: "[{{ __name__ }}][{{ _body_stream }}]"\nactions: []\n'
    )

    rendered = render_pipeline_with_templates(
        config, templates, compile_schemas=False, project_root=tmp_path
    )

    assert "[][]" in rendered
    assert ".j2" not in rendered


def test_underscore_names_are_not_registered_because_jinja_does_not_export_them(
    tmp_path: Path, templates: Path, caplog: pytest.LogCaptureFixture
):
    (templates / "a.j2").write_text(
        "{% set _hidden = 'from-a' %}{% macro _priv() %}a{% endmacro %}\n"
    )
    (templates / "b.j2").write_text(
        "{% set _hidden = 'from-b' %}{% macro _priv() %}b{% endmacro %}\n"
    )
    config = tmp_path / "wf.yml"
    config.write_text('name: wf\ndescription: "[{{ _hidden }}]"\nactions: []\n')

    with caplog.at_level(logging.WARNING):
        rendered = render_pipeline_with_templates(
            config, templates, compile_schemas=False, project_root=tmp_path
        )

    assert "[]" in rendered
    assert "from-a" not in rendered
    assert "from-b" not in rendered
    assert _redefinition_warnings(caplog) == []


def test_exported_names_still_reach_the_workflow(tmp_path: Path, templates: Path):
    (templates / "vars.j2").write_text("{% set house_style = 'formal' %}\n")
    (templates / "macros.j2").write_text("{% macro shout(word) %}{{ word|upper }}{% endmacro %}\n")
    config = tmp_path / "wf.yml"
    config.write_text('name: "{{ house_style }}-{{ shout("wf") }}"\nactions: []\n')

    rendered = render_pipeline_with_templates(
        config, templates, compile_schemas=False, project_root=tmp_path
    )

    assert "formal-WF" in rendered
