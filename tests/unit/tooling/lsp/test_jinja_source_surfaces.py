"""What the editor shows for a workflow that renders through Jinja: diagnostics, outline, hover."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.handlers import build_hover_content
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import Location, Reference, ReferenceType
from agent_actions.tooling.lsp.server import document_symbols, server

_BRANCH = """\
{% macro branch_a(p) -%}
- name: {{ p }}__extract
  kind: tool
  guard:
    condition: nosuch.flag == true
    on_false: filter
{%- endmacro %}
"""


def _project(tmp_path: Path, workflows: dict[str, str]) -> dict[str, Path]:
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "branch_a.jinja2").write_text(_BRANCH)
    paths = {}
    for name, text in workflows.items():
        config = tmp_path / "agent_workflow" / name / "agent_config"
        config.mkdir(parents=True)
        paths[name] = config / f"{name}.yml"
        paths[name].write_text(textwrap.dedent(text))
    return paths


_WORKFLOW = """\
{% from 'branch_a.jinja2' import branch_a %}
name: wf_a
actions:
  {{ branch_a('a') | indent(2) }}
  - name: local_action
    kind: tool
    dependencies: [a__extract]
"""


def test_render_error_publishes_one_diagnostic(tmp_path):
    paths = _project(tmp_path, {"wf_bad": "{% if %}\nactions:\n  - name: x\n", "wf_a": _WORKFLOW})
    idx = build_index(tmp_path)

    diags = collect_diagnostics(paths["wf_bad"], idx)

    assert [(d.range.start.line, d.severity) for d in diags] == [(0, lsp.DiagnosticSeverity.Error)]
    assert diags[0].message.startswith("Workflow does not render: ")
    good = [d.message for d in collect_diagnostics(paths["wf_a"], idx)]
    assert not [m for m in good if m.startswith("Workflow does not render")]
    assert set(idx.workflow_actions["wf_a"]) == {"a__extract", "local_action"}


def test_plain_yaml_error_publishes_its_line(tmp_path):
    paths = _project(tmp_path, {"wf_bad": "name: wf_bad\nactions:\n  - name: x\n   kind: tool\n"})
    idx = build_index(tmp_path)

    diags = collect_diagnostics(paths["wf_bad"], idx)

    assert [(d.range.start.line, d.severity) for d in diags] == [(3, lsp.DiagnosticSeverity.Error)]


def _symbols(file_path: Path, idx) -> list[str]:
    server.project_indexes.clear()
    server.project_indexes[idx.root] = idx
    workspace = MagicMock()
    with patch.object(
        type(server), "workspace", new_callable=lambda: property(lambda s: workspace)
    ):
        params = lsp.DocumentSymbolParams(
            text_document=lsp.TextDocumentIdentifier(uri=file_path.as_uri())
        )
        try:
            return [s.name for s in document_symbols(params)]
        finally:
            server.project_indexes.clear()


def test_outline_lists_only_actions_in_this_file(tmp_path):
    paths = _project(tmp_path, {"wf_a": _WORKFLOW})
    idx = build_index(tmp_path.resolve())

    assert set(idx.file_actions[paths["wf_a"].resolve()]) == {"a__extract", "local_action"}
    assert _symbols(paths["wf_a"].resolve(), idx) == ["local_action"]


def test_macro_action_guard_warning_sits_in_the_workflow_file(tmp_path):
    paths = _project(tmp_path, {"wf_a": _WORKFLOW})
    idx = build_index(tmp_path)

    guard = [d for d in collect_diagnostics(paths["wf_a"], idx) if "nosuch" in d.message]

    # The macro's guard line is 4 in the template; in the workflow it would point at the
    # `{{ branch_a(...) }}` call's neighbour, so it is placed at the top and named.
    assert [d.range.start.line for d in guard] == [0]
    assert guard[0].message.endswith("(defined at templates/branch_a.jinja2 line 2)")


def test_duplicate_macro_action_is_anchored_in_the_workflow_file(tmp_path):
    paths = _project(
        tmp_path,
        {
            "wf_a": """\
            {% from 'branch_a.jinja2' import branch_a %}
            actions:
              {{ branch_a('a') | indent(2) }}
              {{ branch_a('a') | indent(2) }}
            """
        },
    )
    idx = build_index(tmp_path)

    dup = [d for d in collect_diagnostics(paths["wf_a"], idx) if "Duplicate" in d.message]

    assert [(d.range.start.line, d.message) for d in dup] == [
        (
            0,
            "Duplicate action name `a__extract` defined in this workflow"
            " (defined at templates/branch_a.jinja2 line 2).",
        )
    ]


def test_local_duplicate_keeps_its_own_line(tmp_path):
    paths = _project(
        tmp_path,
        {"wf_a": "actions:\n  - name: x\n    kind: tool\n  - name: x\n    kind: tool\n"},
    )
    idx = build_index(tmp_path)

    dup = [d for d in collect_diagnostics(paths["wf_a"], idx) if "Duplicate" in d.message]

    assert [(d.range.start.line, d.message) for d in dup] == [
        (3, "Duplicate action name `x` defined in this workflow.")
    ]


def test_hover_on_macro_action_names_its_template(tmp_path):
    paths = _project(tmp_path, {"wf_a": _WORKFLOW})
    idx = build_index(tmp_path)
    ref = Reference(ReferenceType.ACTION, "a__extract", Location(paths["wf_a"], 6), "a__extract")

    hover = build_hover_content(ref, idx, paths["wf_a"])

    assert hover.endswith("_Defined at `templates/branch_a.jinja2` line 2_")
    local = Reference(ReferenceType.ACTION, "local_action", Location(paths["wf_a"], 6), "x")
    assert build_hover_content(local, idx, paths["wf_a"]).endswith("_Defined at line 5_")
