"""The index holds the actions a workflow renders to, located in the file that defines each one."""

import textwrap
from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import Location, ReferenceType

_BRANCH = """\
{{% macro branch_{x}(p) -%}}
- name: {{{{ p }}}}__extract
  kind: tool
  intent: extract for {{{{ p }}}}
{{%- endmacro %}}
"""

_TEMPLATES = {"branch_a.jinja2": _BRANCH.format(x="a"), "branch_b.jinja2": _BRANCH.format(x="b")}


def _project(tmp_path: Path, workflows: dict[str, str], templates: dict[str, str] | None = None):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    if templates is not None:
        (tmp_path / "templates").mkdir()
        for name, text in templates.items():
            (tmp_path / "templates" / name).write_text(text)
    paths = {}
    for name, text in workflows.items():
        config = tmp_path / "agent_workflow" / name / "agent_config"
        config.mkdir(parents=True)
        paths[name] = config / f"{name}.yml"
        paths[name].write_text(textwrap.dedent(text))
    return paths


_TWO_BRANCHES = """\
{% from 'branch_a.jinja2' import branch_a %}
{% from 'branch_b.jinja2' import branch_b %}
name: wf_a
actions:
  {{ branch_a('a') | indent(2) }}
  {{ branch_b('b') | indent(2) }}
  - name: local_action
    kind: tool
    dependencies: [b__extract, missing]
"""


def test_macro_actions_are_indexed_per_workflow(tmp_path):
    paths = _project(tmp_path, {"wf_a": _TWO_BRANCHES}, _TEMPLATES)

    idx = build_index(tmp_path)

    assert set(idx.workflow_actions["wf_a"]) == {"a__extract", "b__extract", "local_action"}
    assert idx.workflow_actions["wf_a"]["b__extract"] == Location(
        tmp_path / "templates/branch_b.jinja2", line=1, column=8, end_line=1, end_column=18
    )
    meta = idx.file_actions[paths["wf_a"]]["a__extract"]
    assert meta.location.file_path == tmp_path / "templates/branch_a.jinja2"
    assert idx.file_actions[paths["wf_a"]]["local_action"].location.line == 6
    assert idx.parse_errors == {}


def test_two_workflows_share_one_template(tmp_path):
    shared = """\
    {% from 'branch_a.jinja2' import branch_a %}
    actions:
      {{ branch_a('a') | indent(2) }}
    """
    _project(tmp_path, {"wf_a": shared, "wf_b": shared}, _TEMPLATES)

    idx = build_index(tmp_path)

    assert "a__extract" in idx.workflow_actions["wf_a"]
    assert "a__extract" in idx.workflow_actions["wf_b"]


def test_dependency_on_macro_action_resolves(tmp_path):
    paths = _project(tmp_path, {"wf_a": _TWO_BRANCHES}, _TEMPLATES)

    idx = build_index(tmp_path)

    # `missing` is the positive control: the same file still reports what does not exist.
    msgs = [d.message for d in collect_diagnostics(paths["wf_a"], idx)]
    assert msgs == ["Unresolved action reference `missing`."]


def test_jinja_name_line_in_the_workflow_is_not_an_action(tmp_path):
    paths = _project(
        tmp_path,
        {
            "wf_a": """\
            actions:
            {% for p in ['a', 'b'] %}
              - name: {{ p }}_step
                kind: tool
            {% endfor %}
            """
        },
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[paths["wf_a"]]) == {"a_step", "b_step"}
    assert idx.file_actions[paths["wf_a"]]["b_step"].location == Location(
        paths["wf_a"], line=2, column=10, end_line=2, end_column=16
    )


def test_render_error_keeps_workflow_listed(tmp_path):
    paths = _project(
        tmp_path,
        {
            "wf_bad": "{% if %}\nactions:\n  - name: x\n    kind: tool\n",
            "wf_good": "actions:\n  - name: y\n    kind: tool\n",
        },
    )

    idx = build_index(tmp_path)

    bad = paths["wf_bad"]
    assert "wf_bad" in idx.workflows
    assert idx.parse_errors[bad].location == Location(bad, line=0)
    assert idx.parse_errors[bad].message
    assert idx.file_actions[bad] == {}
    assert idx.references_by_file[bad] == []
    assert set(idx.workflow_actions["wf_good"]) == {"y"}
    assert paths["wf_good"] not in idx.parse_errors


def test_duplicate_rendered_action_is_flagged(tmp_path):
    paths = _project(
        tmp_path,
        {
            "wf_a": """\
            {% from 'branch_a.jinja2' import branch_a %}
            actions:
              {{ branch_a('a') | indent(2) }}
              {{ branch_a('a') | indent(2) }}
              - name: once
                kind: tool
            """
        },
        _TEMPLATES,
    )

    idx = build_index(tmp_path)

    assert idx.duplicate_actions_by_file[paths["wf_a"]] == {"a__extract"}


def test_plain_project_index_unchanged(tmp_path):
    paths = _project(
        tmp_path,
        {
            "wf_a": """\
            name: wf_a
            actions:
              - name: extract
                kind: tool
                impl: do_extract
              - name: judge
                dependencies:
                  - extract
                schema: verdict
                prompt: $wf_a.Judge
                context_scope:
                  observe:
                    - extract.text
            """
        },
    )

    idx = build_index(tmp_path)

    # The values main produced for this file before workflows were rendered.
    wf = paths["wf_a"]
    assert idx.file_actions[wf]["extract"].location == Location(wf, 2, 10, 2, 17)
    assert idx.file_actions[wf]["judge"].location == Location(wf, 5, 10, 5, 15)
    refs = [
        (r.type, r.value, r.location.line, r.location.column) for r in idx.references_by_file[wf]
    ]
    assert refs == [
        (ReferenceType.TOOL, "do_extract", 4, 10),
        (ReferenceType.ACTION, "extract", 7, 8),
        (ReferenceType.SCHEMA, "verdict", 8, 12),
        (ReferenceType.PROMPT, "wf_a.Judge", 9, 12),
        (ReferenceType.CONTEXT_FIELD, "extract.text", 12, 10),
    ]
    assert idx.duplicate_actions_by_file[wf] == set()
    assert idx.parse_errors == {}
