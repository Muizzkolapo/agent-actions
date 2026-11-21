"""The index sees what the render of `agac` produces, and nothing the render removes."""

import textwrap
from pathlib import Path

import pytest
import yaml

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.jinja_source import WorkflowRenderError, render_workflow_source


def _project(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> Path:
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    (tmp_path / "templates").mkdir()
    for name, text in (templates or {}).items():
        (tmp_path / "templates" / name).write_text(text)
    config = tmp_path / "agent_workflow" / "wf" / "agent_config"
    config.mkdir(parents=True)
    wf = config / "wf.yml"
    wf.write_text(textwrap.dedent(workflow))
    return wf


def _messages(wf: Path, tmp_path: Path) -> list[str]:
    return [d.message for d in collect_diagnostics(wf, build_index(tmp_path))]


def test_an_action_in_a_branch_that_does_not_render_is_not_indexed(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set mode = 'fast' %}
        name: wf
        actions:
        {% if mode == 'fast' %}
          - name: summarize
            kind: tool
        {% else %}
          - name: summarize
            kind: tool
        {% endif %}
          - name: use
            kind: tool
            dependencies: [debug_action]
        {% if false %}
          - name: debug_action
            kind: tool
        {% endif %}
        """,
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"summarize", "use"}
    assert idx.file_actions[wf]["summarize"].location.line == 4
    assert idx.duplicate_actions_by_file[wf] == set()
    # The reference to the action that does not render is the live control.
    assert _messages(wf, tmp_path) == ["Unresolved action reference `debug_action`."]


def test_a_line_that_does_not_render_gives_no_reference(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
          - name: x
            kind: tool
            {% if false %}
            dependencies: [nope]
            {% endif %}
          - name: y
            kind: tool
            dependencies: [missing]
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_jinja_in_a_dependency_list_gives_no_false_reference(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
          - name: a__x
            kind: tool
          - name: flow
            kind: tool
            dependencies: [{% for p in ['a'] %}{{ p }}__x{% endfor %}]
          - name: block
            kind: tool
            dependencies:
            {% for p in ['a'] %}
              - {{ p }}__x
            {% endfor %}
              - missing
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_an_action_in_a_jinja_comment_is_not_indexed(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
          - name: kept
            kind: tool
        {#
          - name: ghost
            kind: tool
        #}
        """,
    )

    assert set(build_index(tmp_path).file_actions[wf]) == {"kept"}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("\"{{ 'a' + 1 }}\"", id="type-error"),
        pytest.param("\"{{ load_prompt('nope.missing') }}\"", id="missing-prompt"),
    ],
)
def test_any_render_failure_is_one_error_diagnostic(tmp_path, value):
    wf = _project(tmp_path, f"description: {value}\nactions:\n  - name: x\n    kind: tool\n")

    idx = build_index(tmp_path)

    assert idx.parse_errors[wf].location.line == 0
    diags = collect_diagnostics(wf, idx)
    assert [d.message.startswith("Workflow does not render: ") for d in diags] == [True]


def test_the_yaml_step_is_the_one_agac_uses(tmp_path):
    # PyYAML's safe_load, which agac uses, keeps the last of two equal keys; ruamel refuses.
    text = "actions:\n  - name: a\n    impl: t\n    impl: u\n    kind: tool\n"
    wf = _project(tmp_path, text)

    r = render_workflow_source(wf, tmp_path)

    assert r.data == yaml.safe_load(text)
    assert r.data["actions"][0]["impl"] == "u"
    assert build_index(tmp_path).parse_errors == {}


def test_a_strip_tag_ending_a_name_line_keeps_later_lines_in_place(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
          - name: {{ 'a' -}}
        {{ '' }}
            kind: tool
          - name: b
            kind: tool
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a", "b"]
    assert r.action_sources["b"].line == 4


def test_a_multiline_set_tag_keeps_its_actions_mapped(tmp_path):
    # The shape of ql_compact: a dict literal that spans lines inside one `{% set %}`.
    wf = _project(
        tmp_path,
        """\
        {% set profiles = {
          'fast': {'vendor': 'x'},
          'slow': {'vendor': 'y'}} %}
        actions:
          - name: a
            kind: tool
            intent: {{ profiles.fast.vendor }}
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert r.data["actions"][0]["intent"] == "x"
    assert r.action_sources["a"].line == 4


def test_a_yaml_error_in_a_jinja_file_names_the_rendered_line(tmp_path):
    wf = _project(tmp_path, "{% set v = 'tool' %}\nactions:\n  - name: x\n   kind: {{ v }}\n")

    with pytest.raises(WorkflowRenderError) as e:
        render_workflow_source(wf, tmp_path)

    assert e.value.line == 0
    assert "of the rendered workflow" in e.value.message


_PROMPT_NAMES_AN_ACTION = """\
actions:
  - name: writer
    kind: tool
    prompt: |
      Write YAML like this:
      - name: other_action
    dependencies: [missing]
  - name: other_action
    kind: tool
"""


def test_a_prompt_line_naming_an_action_is_not_indexed_as_one(tmp_path):
    # Plain YAML, so no line is dropped: only the defined-line rule tells the two apart.
    wf = _project(tmp_path, _PROMPT_NAMES_AN_ACTION)

    idx = build_index(tmp_path)

    assert idx.duplicate_actions_by_file[wf] == set()
    assert idx.file_actions[wf]["other_action"].location.line == 7


def test_a_prompt_line_naming_an_action_does_not_end_its_action(tmp_path):
    wf = _project(tmp_path, _PROMPT_NAMES_AN_ACTION)

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_template_line_number_does_not_revive_a_dropped_workflow_line(tmp_path):
    # The macro's name line and the dropped dependency line are both line 6.
    wf = _project(
        tmp_path,
        "{% from 'm.jinja2' import m %}\n"
        "actions:\n"
        "  {{ m('a') | indent(2) }}\n"
        "  - name: y\n"
        "    kind: tool\n"
        "    {% if false %}\n"
        "    dependencies: [nope]\n"
        "    {% endif %}\n"
        "  - name: z\n"
        "    kind: tool\n"
        "    dependencies: [missing]\n",
        {
            "m.jinja2": "{# pad #}\n" * 5
            + "{% macro m(p) -%}\n- name: {{ p }}__x\n  kind: tool\n{%- endmacro %}\n"
        },
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_set_block_value_is_read_as_the_render_reads_it(tmp_path):
    # A mark inside `{% set %}...{% endset %}` would change the captured value, and the
    # marked render would take the other branch.
    wf = _project(
        tmp_path,
        """\
        {% set mode %}
        fast
        {% endset %}
        name: wf
        actions:
        {% if mode | trim == 'fast' %}
          - name: summarize
            kind: tool
            impl: fast_tool
        {% else %}
          - name: summarize_slow
            kind: tool
            impl: slow_tool
        {% endif %}
        """,
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"summarize"}
    assert idx.file_actions[wf]["summarize"].location.line == 6
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `fast_tool`."]


def test_a_set_block_split_into_actions_keeps_their_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set stages %}
        extract
        summarize
        {% endset %}
        actions:
        {% for s in stages.split() %}
          - name: {{ s }}
            kind: tool
        {% endfor %}
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["extract", "summarize"]
    assert r.action_sources["extract"].line == 6
    assert r.action_sources["summarize"].line == 6


_BRANCH_ON_MODE = """\
name: wf
actions:
{% if mode | trim == 'fast' %}
  - name: summarize
    kind: tool
    impl: fast_tool
{% else %}
  - name: summarize_slow
    kind: tool
    impl: slow_tool
{% endif %}
"""


@pytest.mark.parametrize(
    "opener",
    [
        pytest.param("{% set vendor = 'x' %}\n{% set mode %}", id="after-an-inline-set"),
        pytest.param("{%+ set mode %}", id="plus-modifier"),
        pytest.param("{% set mode | replace('x', 'y', count=1) %}", id="filter-keyword-argument"),
    ],
)
def test_every_spelling_of_a_set_block_is_read_as_the_render_reads_it(tmp_path, opener):
    wf = _project(tmp_path, f"{opener}\nfast\n{{% endset %}}\n{_BRANCH_ON_MODE}")
    offset = opener.count("\n")

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"summarize"}
    assert idx.file_actions[wf]["summarize"].location.line == 6 + offset
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `fast_tool`."]


def test_a_name_line_in_a_set_block_is_read_as_the_render_reads_it(tmp_path):
    wf = _project(
        tmp_path,
        "{% set first %}\n- name: extract\n{% endset %}\n"
        + _BRANCH_ON_MODE.replace("mode | trim == 'fast'", "first | trim == '- name: extract'"),
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"summarize"}
    assert idx.file_actions[wf]["summarize"].location.line == 6


def test_the_body_of_a_macro_never_called_gives_no_reference(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
            impl: real_tool
        {% macro unused() %}
            impl: ghost_tool
        {% endmacro %}
          - name: b
            kind: tool
        """,
    )

    idx = build_index(tmp_path)

    assert idx.file_actions[wf]["a"].impl_ref == "real_tool"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `real_tool`."]


def test_a_macro_in_the_workflow_file_maps_its_actions_to_its_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro step(p) -%}
        - name: {{ p }}__step
          kind: tool
        {%- endmacro %}
        actions:
          {{ step('a') | indent(2) }}
          {{ step('b') | indent(2) }}
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a__step", "b__step"]
    assert r.action_sources["a__step"].line == 1
    assert r.action_sources["b__step"].line == 1
