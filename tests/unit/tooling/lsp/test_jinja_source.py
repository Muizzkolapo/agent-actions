"""The editor's render of a workflow: same Jinja step as `agac`, each action mapped to its source
line."""

import textwrap
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from agent_actions.errors import ConfigurationError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.tooling.lsp.jinja_source import WorkflowRenderError, render_workflow_source
from agent_actions.tooling.lsp.models import Location

_BRANCH = """\
{{% macro branch_{x}(p) -%}}
- name: {{{{ p }}}}__extract
  kind: tool
  impl: noop_{x}
{{%- endmacro %}}
"""


def _project(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> Path:
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    if templates is not None:
        (tmp_path / "templates").mkdir()
        for name, text in templates.items():
            (tmp_path / "templates" / name).write_text(text)
    config = tmp_path / "agent_workflow" / "wf_a" / "agent_config"
    config.mkdir(parents=True)
    wf = config / "wf_a.yml"
    wf.write_text(textwrap.dedent(workflow))
    return wf


def _two_branch_project(tmp_path: Path) -> Path:
    return _project(
        tmp_path,
        """\
        {% from 'branch_a.jinja2' import branch_a %}
        {% from 'branch_b.jinja2' import branch_b %}
        name: wf_a
        actions:
          {{ branch_a('a') | indent(2) }}
          {{ branch_b('b') | indent(2) }}
          - name: local_action
            kind: tool
            impl: noop
            dependencies: [b__extract]
        """,
        {"branch_a.jinja2": _BRANCH.format(x="a"), "branch_b.jinja2": _BRANCH.format(x="b")},
    )


def test_macro_actions_map_to_their_own_template_line(tmp_path):
    wf = _two_branch_project(tmp_path)

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a__extract", "b__extract", "local_action"]
    assert r.action_sources["a__extract"] == Location(
        tmp_path / "templates/branch_a.jinja2", line=1, column=8, end_line=1, end_column=18
    )
    assert r.action_sources["b__extract"].file_path == tmp_path / "templates/branch_b.jinja2"
    assert r.action_sources["b__extract"].line == 1
    assert r.action_sources["local_action"] == Location(
        wf, line=6, column=10, end_line=6, end_column=22
    )
    assert "@src" not in r.text
    assert "{{" not in r.text


def test_plain_yaml_maps_to_workflow_file(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf_a
        actions:
          - kind: tool
            name: x
            impl: noop
          - name: 'y'
            kind: tool
            impl: noop
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert r.data == YAML(typ="safe").load(wf.read_text())
    assert r.action_sources["x"] == Location(wf, line=3, column=10, end_line=3, end_column=11)
    assert r.action_sources["y"] == Location(wf, line=5, column=11, end_line=5, end_column=12)


def test_whitespace_control_after_name_keeps_data(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set flag = true %}
        actions:
          - name: x
          {%- if flag %}
            kind: tool
          {%- endif %}
            impl: noop
          - name: y
            kind: tool
            impl: noop
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["x", "y"]
    assert r.data["actions"][0]["kind"] == "tool"
    assert r.action_sources["x"].line == 2
    assert r.action_sources["y"].line == 7


def test_a_prompt_line_naming_an_action_does_not_take_its_location(tmp_path):
    # The prompt line `- name: other_action` comes BEFORE the real definition, so a
    # first-mark-by-name rule would take it; only the line of the parsed action counts.
    wf = _project(
        tmp_path,
        """\
        actions:
          - name: writer
            kind: tool
            impl: noop
            prompt: |
              Write YAML like this:
              - name: other_action
          - name: other_action
            kind: tool
            impl: noop
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert r.action_sources["other_action"] == Location(
        wf, line=7, column=10, end_line=7, end_column=22
    )
    assert r.data["actions"][0]["prompt"] == "Write YAML like this:\n- name: other_action\n"


def test_jinja_syntax_error_raises_with_line(tmp_path):
    wf = _project(tmp_path, "name: wf_a\nactions:\n  - name: {{ x \n")

    with pytest.raises(WorkflowRenderError) as e:
        render_workflow_source(wf, tmp_path)

    assert e.value.line == 2
    assert e.value.message


def test_yaml_error_in_plain_file_raises_with_line(tmp_path):
    # Line 3 indents `kind` one column short of `name`, which YAML rejects there.
    wf = _project(tmp_path, "name: wf_a\nactions:\n  - name: x\n   kind: tool\n")

    with pytest.raises(WorkflowRenderError) as e:
        render_workflow_source(wf, tmp_path)

    assert e.value.line == 3


def test_template_syntax_error_names_the_template(tmp_path):
    wf = _project(
        tmp_path,
        "{% from 'branch_a.jinja2' import branch_a %}\nactions:\n  {{ branch_a('a') }}\n",
        {"branch_a.jinja2": "{% macro branch_a(p) %}\n- name: {{ p \n{% endmacro %}\n"},
    )

    with pytest.raises(WorkflowRenderError) as e:
        render_workflow_source(wf, tmp_path)

    assert e.value.line == 0
    assert "branch_a.jinja2" in e.value.message


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*")}


def test_render_writes_no_file(tmp_path):
    wf = _project(
        tmp_path,
        "{% set v = 'tool' %}\nactions:\n  - name: x\n   kind: [{{ v }}\n",
    )
    # Positive control: the runtime path writes a failed-render file for this input,
    # so a listing of the tree does see a write.
    before = _files(tmp_path)
    with pytest.raises(ConfigurationError):
        render_pipeline_with_templates(
            wf, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    assert _files(tmp_path) - before

    before = _files(tmp_path)
    with pytest.raises(WorkflowRenderError):
        render_workflow_source(wf, tmp_path)
    assert _files(tmp_path) == before
