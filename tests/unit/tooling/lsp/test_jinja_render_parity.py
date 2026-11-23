"""The index sees what the render of `agac` produces, and nothing the render removes."""

import textwrap
from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.jinja_source import WorkflowRenderError, render_workflow_source
from agent_actions.tooling.lsp.models import ReferenceType


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


def _project_without_templates_folder(tmp_path: Path, workflow: str) -> Path:
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
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
        pytest.param("{% set (a, b) = (1, 2) %}\n{% set mode %}", id="after-a-tuple-assignment"),
        pytest.param("{% set a, b = 1, 2 %}\n{% set mode %}", id="after-a-pair-assignment"),
        pytest.param(
            "{% set ns = namespace(m='x') %}\n{% set ns.m = 'y' %}\n{% set mode %}",
            id="after-a-namespace-assignment",
        ),
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


@pytest.mark.parametrize("closer", ["{%- endset %}", "{%+ endset %}"])
def test_every_spelling_of_a_set_block_close_is_read_as_the_render_reads_it(tmp_path, closer):
    wf = _project(tmp_path, f"{{% set mode %}}\nfast\n{closer}\n{_BRANCH_ON_MODE}")

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"summarize"}
    assert idx.file_actions[wf]["summarize"].location.line == 6
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `fast_tool`."]


def test_a_unicode_line_separator_in_a_value_keeps_every_reference(tmp_path):
    wf = _project(
        tmp_path,
        'name: wf\ndescription: "first\u2028second"\nactions:\n'
        "  - name: a\n    kind: tool\n    impl: ta\n"
        "  - name: b\n    kind: tool\n    impl: tb\n    dependencies:\n      - a\n      "
        "- missing\n",
    )

    assert render_workflow_source(wf, tmp_path).action_sources["b"].line == 6
    assert sorted(_messages(wf, tmp_path)) == [
        "Unresolved action reference `missing`.",
        "Unresolved tool reference `ta`.",
        "Unresolved tool reference `tb`.",
    ]


def test_a_unicode_line_separator_before_a_last_name_line_keeps_the_actions(tmp_path):
    wf = _project(
        tmp_path,
        'name: wf\ndescription: "first\u2028second"\nactions:\n  - name: a\n    kind: '
        "tool\n  - name: zed",
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"a", "zed"}
    assert idx.file_actions[wf]["zed"].location.line == 5


def test_a_workflow_from_the_prompt_store_loads_as_agac_loads_it(tmp_path):
    wf = _project(tmp_path, "$wfbody.main\n")
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "wfbody.md").write_text(
        "{prompt main}\nname: wf\nactions:\n  - name: a\n    kind: tool\n{end_prompt}\n"
    )
    agac = yaml.safe_load(
        render_pipeline_with_templates(
            wf, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    )

    r = render_workflow_source(wf, tmp_path)
    idx = build_index(tmp_path)

    assert [a["name"] for a in agac["actions"]] == ["a"]
    assert [a["name"] for a in r.data["actions"]] == ["a"]
    assert idx.parse_errors == {}
    assert set(idx.file_actions[wf]) == {"a"}


def test_raw_text_gives_references_only_where_it_renders(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
        {% if false %}
        {% raw %}
            impl: dead_tool
            dependencies: [ghost]
        {% endraw %}
        {% endif %}
          - name: b
            kind: tool
        {% raw %}
            dependencies: [missing]
        {% endraw %}
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_text_that_a_call_block_outputs_as_written_gives_its_references(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro wrap() %}{{ caller() }}{% endmacro %}
        name: wf
        actions:
          - name: two
            kind: tool
        {% call wrap() %}
            impl: tool_i
            dependencies: [outer]
        {% endcall %}
        """,
    )

    assert sorted(_messages(wf, tmp_path)) == [
        "Unresolved action reference `outer`.",
        "Unresolved tool reference `tool_i`.",
    ]


_PICK_BY_HELD_VALUE = """\
{% macro pick() %}
{% set label %}
- name: x
{% endset %}
{% if label | trim == '- name: x' %}
  - name: a__yes
    kind: tool
{% else %}
  - name: a__no
    kind: tool
{% endif %}
{% endmacro %}
"""


def test_a_set_block_in_a_workflow_macro_is_read_as_the_render_reads_it(tmp_path):
    wf = _project(tmp_path, _PICK_BY_HELD_VALUE + "name: wf\nactions:\n{{ pick() }}\n")

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a__yes"]
    assert r.action_sources["a__yes"].file_path == wf
    assert r.action_sources["a__yes"].line == 5


def test_a_set_block_in_a_template_macro_is_read_as_the_render_reads_it(tmp_path):
    wf = _project(
        tmp_path,
        "{% from 'm.jinja2' import pick %}\nname: wf\nactions:\n{{ pick() }}\n",
        {"m.jinja2": _PICK_BY_HELD_VALUE},
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a__yes"]
    assert r.action_sources["a__yes"].file_path == tmp_path / "templates" / "m.jinja2"
    assert r.action_sources["a__yes"].line == 5


def test_marks_that_change_the_render_give_no_wrong_source_line(tmp_path):
    # The macro output is held and tested; its name mark would take the other branch.
    wf = _project(
        tmp_path,
        """\
        {% macro m() %}
        - name: q
        {% endmacro %}
        {% set x = m() %}
        name: wf
        actions:
        {% if x | trim == '- name: q' %}
          - name: shown
            kind: tool
        {% else %}
          - name: hidden
            kind: tool
        {% endif %}
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["shown"]
    assert r.action_sources.get("shown", None) is None or r.action_sources["shown"].line == 7
    assert build_index(tmp_path).file_actions[wf]["shown"].location.line == 7


def test_an_action_in_a_call_block_maps_to_its_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro wrap() %}{{ caller() }}{% endmacro %}
        name: wf
        actions:
        {% call wrap() %}
          - name: inner
            kind: tool
        {% endcall %}
        {% if false %}
          - name: inner
            kind: tool
        {% endif %}
        """,
    )

    assert render_workflow_source(wf, tmp_path).action_sources["inner"].line == 4


def test_a_template_name_line_does_not_make_a_workflow_prompt_line_an_action(tmp_path):
    # The macro's name line and the prompt line that names the same action are both line 5.
    wf = _project(
        tmp_path,
        "{% from 'm.jinja2' import m %}\n"
        "actions:\n"
        "  - name: writer\n"
        "    kind: tool\n"
        "    prompt: |\n"
        "      - name: a__x\n"
        "  {{ m('a') | indent(2) }}\n",
        {
            "m.jinja2": "{# pad #}\n" * 4
            + "{% macro m(p) -%}\n- name: {{ p }}__x\n  kind: tool\n{%- endmacro %}\n"
        },
    )

    location = build_index(tmp_path).file_actions[wf]["a__x"].location

    assert location.file_path == tmp_path / "templates" / "m.jinja2"
    assert location.line == 5


def test_a_filter_body_with_a_dropped_line_gives_no_reference_from_it(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
        {% filter indent(2) %}
        - name: a
          kind: tool
        {% if false %}
          dependencies:
            - ghost
        {% endif %}
        {% endfilter %}
          - name: b
            kind: tool
            dependencies: [missing]
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_filter_block_in_a_dropped_branch_gives_no_reference(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
            dependencies: [missing]
        {% if false %}
        {% filter trim %}
          - name: z
            kind: tool
            dependencies: [ghost]
        {% endfilter %}
        {% endif %}
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


@pytest.mark.parametrize(
    ("emitter", "templates"),
    [
        pytest.param(
            "{% call act('b') %}\n    impl: t2\n    dependencies: [a]\n{% endcall %}\n",
            {},
            id="call",
        ),
        pytest.param(
            "{% include 'b.jinja2' %}\n    impl: t2\n    dependencies: [a]\n",
            {"b.jinja2": "  - name: b\n    kind: tool\n"},
            id="include",
        ),
    ],
)
def test_lines_under_a_tag_that_outputs_an_action_are_not_the_action_above(
    tmp_path, emitter, templates
):
    wf = _project(
        tmp_path,
        "{% macro act(n) %}\n  - name: {{ n }}\n    kind: tool\n{{ caller() }}\n{%- endmacro %}\n"
        "name: wf\nactions:\n  - name: a\n    kind: tool\n    impl: t1\n" + emitter,
        templates,
    )

    idx = build_index(tmp_path)

    assert {
        a["name"]: a.get("impl") for a in render_workflow_source(wf, tmp_path).data["actions"]
    } == {
        "a": "t1",
        "b": "t2",
    }
    assert idx.file_actions[wf]["a"].impl_ref == "t1"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `t1`."]


def test_a_workflow_whose_marks_change_the_render_reads_no_dropped_line(tmp_path):
    # The macro output is held and tested, so the marks take the other branch, which has
    # one more line; no line of the file can then be read as live.
    wf = _project(
        tmp_path,
        """\
        {% macro m() %}
        - name: q
        {% endmacro %}
        {% set x = m() %}
        name: wf
        actions:
        {% if x | trim == '- name: q' %}
          - name: shown
            kind: tool
            impl: live_tool
        {% else %}
          - name: shown
            kind: tool
            impl: dead_tool
            description: only in the branch that does not render
        {% endif %}
        """,
    )

    idx = build_index(tmp_path)

    assert [a["impl"] for a in render_workflow_source(wf, tmp_path).data["actions"]] == [
        "live_tool"
    ]
    assert set(idx.file_actions[wf]) == {"shown"}
    assert idx.file_actions[wf]["shown"].location.line == 7
    assert idx.duplicate_actions_by_file[wf] == set()
    assert not any("dead_tool" in m for m in _messages(wf, tmp_path))


def test_a_name_written_as_a_multiline_tag_maps_to_its_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set prefix = "pre" %}
        name: wf
        actions:
          - name: {{ prefix ~
              "_x" }}
            kind: tool
        """,
    )

    assert render_workflow_source(wf, tmp_path).action_sources["pre_x"].line == 3
    assert build_index(tmp_path).file_actions[wf]["pre_x"].location.line == 3


def test_a_set_block_spelling_keeps_dropped_lines_out_of_the_index(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set v = 1 %}
        {% set mode %}
        fast
        {%- endset %}
        name: wf
        actions:
          - name: a
            kind: tool
        {% if mode | trim != 'fast' %}
            dependencies: [ghost]
        {% endif %}
          - name: b
            kind: tool
            dependencies: [missing]
        """,
    )

    r = render_workflow_source(wf, tmp_path)

    assert {name: loc.line for name, loc in r.action_sources.items()} == {"a": 6, "b": 11}
    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_prompt_store_workflow_puts_its_actions_on_the_one_line_of_the_file(tmp_path):
    wf = _project(tmp_path, "$wfbody.main\n")
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "wfbody.md").write_text(
        "{prompt main}\nname: wf\nactions:\n  - name: a\n    kind: tool\n{end_prompt}\n"
    )

    assert build_index(tmp_path).file_actions[wf]["a"].location.line == 0


def test_a_prompt_store_workflow_read_as_plain_yaml_gets_no_source_lines(tmp_path):
    wf = _project(tmp_path, "$wfbody.main\n", _BROKEN_TEMPLATES)
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "wfbody.md").write_text(
        "{prompt main}\nname: wf\nactions:\n  - name: x\n    kind: tool\n"
        "  - name: a\n    kind: tool\n{end_prompt}\n"
    )

    rendered = render_workflow_source(wf, tmp_path)

    assert [action["name"] for action in rendered.data["actions"]] == ["x", "a"]
    assert rendered.action_sources == {}


def test_a_loop_after_an_action_gives_its_lines_to_no_literal_action(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set ps = ['p1'] %}
        name: wf
        actions:
          - name: a
            kind: tool
        {% for p in ps %}
          - name: {{ p }}_step
            kind: tool
            impl: tool_x
        {% endfor %}
          - name: c
            kind: tool
            impl: tool_c
        """,
    )

    idx = build_index(tmp_path)

    assert idx.file_actions[wf]["a"].impl_ref is None
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_c`."]


_STEP = "{% macro step(n) -%}\n- name: {{ n }}\n  kind: tool\n{%- endmacro %}\n"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            "  {% filter dedent %}\n    dependencies: [ghost]\n  {% endfilter %}\n",
            id="filter-moves-the-text",
        ),
        pytest.param(
            "  {% filter replace('ghost', 'a') %}\n  dependencies: [ghost]\n  {% endfilter %}\n",
            id="filter-changes-the-text",
        ),
    ],
)
def test_a_filter_body_is_not_read_as_written(tmp_path, body):
    wf = _project(tmp_path, "name: wf\nactions:\n- name: a\n  kind: tool\n  impl: tool_a\n" + body)

    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_a`."]


def test_a_filter_body_under_an_emitted_action_is_not_the_action_above(tmp_path):
    wf = _project(
        tmp_path,
        "{% from 'm.jinja2' import emit %}\nname: wf\nactions:\n"
        "- name: a\n  kind: tool\n  impl: tool_a\n  {{ emit('b') }}\n"
        "  {% filter safe %}\n  impl: tool_b\n  {% endfilter %}\n",
        {
            "m.jinja2": "{% macro emit(n) -%}\nx_note: 1\n- name: {{ n }}\n  kind: "
            "tool\n{%- endmacro %}\n"
        },
    )

    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref == "tool_a"


def test_a_name_line_in_a_filter_body_is_not_an_action_definition(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
        - name: b
          kind: tool
          impl: tool_b
        - name: a
          kind: tool
          {% filter safe %}
          inputs:
            - name: b
              note: x
          {% endfilter %}
          impl: tool_a
        """,
    )

    idx = build_index(tmp_path)

    assert idx.file_actions[wf]["b"].location.line == 2
    assert idx.duplicate_actions_by_file[wf] == set()
    assert idx.file_actions[wf]["a"].impl_ref == "tool_a"


def test_a_caller_filter_that_changes_the_body_gives_no_reference_from_it(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro rename(old, new) %}{{ caller() | replace(old, new) }}{% endmacro %}
        name: wf
        actions:
        - name: a
          kind: tool
        {% call rename('ghost', 'real') %}
          impl: ghost_tool
          dependencies: [ghost_up]
        {% endcall %}
        - name: c
          kind: tool
          impl: tool_c
        """,
    )

    assert render_workflow_source(wf, tmp_path).data["actions"][0]["impl"] == "real_tool"
    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref is None
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_c`."]


def test_a_line_that_ends_a_dropped_branch_is_not_read(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set extra = false %}
        name: wf
        actions:
        - name: a
          kind: tool
          {% if extra %}
          schema: ghost_schema {% endif %}
          impl: tool_a
        """,
    )

    meta = build_index(tmp_path).file_actions[wf]["a"]

    assert meta.schema_ref is None
    assert meta.impl_ref == "tool_a"


def test_a_filter_that_changes_a_name_mark_gives_no_source_line(tmp_path):
    wf = _project(
        tmp_path,
        "{% from 'my_steps.jinja2' import step %}\nname: wf\nactions:\n"
        "{{ step('load_raw') | replace('_', '-') }}\n"
        "{{ step('x') | replace('templates/', '') }}\n"
        "{{ step('ok') }}\n",
        {"my_steps.jinja2": _STEP},
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["load-raw", "x", "ok"]
    assert {name: (loc.file_path.name, loc.line) for name, loc in r.action_sources.items()} == {
        "ok": ("my_steps.jinja2", 1)
    }


def test_a_name_that_is_not_a_string_does_not_stop_the_index(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% from 'my_steps.jinja2' import step %}
        {% set up = 'loader' %}
        name: wf
        actions:
        - name: yes
          kind: tool
        - name: b
          kind: tool
          dependencies: [stage_{{ up }}]
        {{ step('stage_loader') }}
        - name: c
          kind: tool
          impl: tool_c
        """,
        {"my_steps.jinja2": _STEP},
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"b", "stage_loader", "c"}
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_c`."]


def test_a_template_blank_line_does_not_revive_a_dropped_workflow_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% from 't.jinja2' import m %}
        actions:
          - name: a
            kind: tool
        {% if false %}
            impl: ghost_tool
        {% endif %}
            dependencies: [missing]
        """,
        {"t.jinja2": "{% macro m() %}\n\n\n\n\n\n{% endmacro %}\n"},
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


@pytest.mark.parametrize(
    ("tail", "templates", "key"),
    [
        pytest.param(
            "{% include 'tail.jinja2' %}\n    impl: ghost_tool\n",
            {"tail.jinja2": "extra:\n"},
            "extra",
            id="include-opens-a-key",
        ),
        pytest.param(
            "{% if true -%}\n    impl: ghost_tool\n{% endif %}\n",
            {},
            None,
            id="strip-tag-joins-lines",
        ),
    ],
)
def test_a_line_the_render_puts_outside_the_last_action_is_not_its_text(
    tmp_path, tail, templates, key
):
    wf = _project(
        tmp_path,
        "name: wf\nactions:\n  - name: a\n    kind: tool\n    dependencies: [missing]\n" + tail,
        templates,
    )

    r = render_workflow_source(wf, tmp_path)

    assert "impl" not in r.data["actions"][0]
    assert (r.data[key] if key else r.data)["impl"] == "ghost_tool"
    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_comment_text_gives_no_reference(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool  {# impl: ghost_tool #}
            dependencies: [missing]
        """,
    )

    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_tag_name_in_a_filter_body_ends_the_action_above(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set p = 'b' %}
        name: wf
        actions:
          - name: a
            kind: tool
        {% filter replace('QQ', 'q') %}
          - name: {{ p }}
            kind: tool
            impl: tool_b
        {% endfilter %}
        """,
    )

    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref is None


def test_marks_that_add_lines_to_the_render_keep_the_actions(tmp_path):
    wf = _project(
        tmp_path,
        "{% macro m() %}\n- name: q\n{% endmacro %}\n{% set x = m() %}\nname: wf\nactions:\n"
        "  - name: a\n    kind: tool\n{% if x | trim != '- name: q' %}\n\nextra: 1{% endif %}",
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["a"]
    assert r.action_sources == {}
    assert set(build_index(tmp_path).file_actions[wf]) == {"a"}


@pytest.mark.parametrize(
    ("block", "b_line"),
    [
        pytest.param(
            "    {% if flag -%}\n    dependencies: [missing]\n    {%- endif %}\n",
            8,
            id="strip-tags",
        ),
        pytest.param(
            "{% filter upper %}\n    impl: x_tool\n{% endfilter %}\n", 8, id="upper-filter"
        ),
    ],
)
def test_a_block_that_changes_its_text_keeps_the_other_actions_mapped(tmp_path, block, b_line):
    wf = _project(
        tmp_path,
        "{% set flag = true %}\nname: wf\nactions:\n  - name: a\n    kind: tool\n"
        + block
        + "  - name: b\n    kind: tool\n",
    )

    assert render_workflow_source(wf, tmp_path).action_sources["b"].line == b_line


def test_a_tag_that_pulls_text_onto_a_name_line_gives_no_false_duplicate(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set v2 = true %}
        actions:
          - name: extract
            kind: tool
            impl: tool_one
          - name: extract
        {%- if v2 %}_v2{% endif %}
            kind: tool
            impl: tool_two
        """,
    )

    idx = build_index(tmp_path)

    assert [a["name"] for a in render_workflow_source(wf, tmp_path).data["actions"]] == [
        "extract",
        "extract_v2",
    ]
    assert idx.duplicate_actions_by_file[wf] == set()
    assert idx.file_actions[wf]["extract"].location.line == 2


_OPENS_CONTEXT_SCOPE = "    context_scope:\n      observe:\n        - setup.x\n"


@pytest.mark.parametrize(
    ("emitter", "templates"),
    [
        pytest.param(
            "{% include 'scope.yml.jinja2' %}\n",
            {"scope.yml.jinja2": _OPENS_CONTEXT_SCOPE},
            id="include",
        ),
        pytest.param(
            "{% from 'common.jinja2' import scope %}    {{ scope() }}\n",
            {
                "common.jinja2": "{% macro scope() -%}\n"
                + _OPENS_CONTEXT_SCOPE.lstrip()
                + "{%- endmacro %}\n"
            },
            id="macro-call",
        ),
    ],
)
def test_a_tag_that_opens_a_key_ends_the_list_above_it(tmp_path, emitter, templates):
    wf = _project(
        tmp_path,
        "actions:\n  - name: setup\n    kind: tool\n  - name: b\n    kind: tool\n"
        "    dependencies:\n      - setup\n" + emitter + "        - setup.y\n"
        "  - name: c\n    kind: tool\n    dependencies: [missing]\n",
        templates,
    )

    observe = render_workflow_source(wf, tmp_path).data["actions"][1]["context_scope"]["observe"]

    assert observe == ["setup.x", "setup.y"]
    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]


def test_a_tag_that_opens_dependencies_ends_the_context_list_above_it(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% from 'common.jinja2' import deps %}
        actions:
          - name: setup
            kind: tool
          - name: b
            kind: tool
            context_scope:
              observe:
                - setup.x
            {{ deps() }}
              - a
          - name: a
            kind: tool
        """,
        {"common.jinja2": "{% macro deps() -%}\ndependencies:\n      - setup\n{%- endmacro %}\n"},
    )

    refs = build_index(tmp_path).references_by_file[wf]

    assert render_workflow_source(wf, tmp_path).data["actions"][1]["dependencies"] == [
        "setup",
        "a",
    ]
    assert [r.type for r in refs if r.value == "a"] in ([], [ReferenceType.ACTION])


def test_the_lines_inside_a_multiline_expression_give_no_reference(tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "pick.jinja2").write_text(
        "{% macro pick(a, b) -%}\n{{ b }}\n{%- endmacro %}\n"
    )
    wf = _project_without_templates_folder(
        tmp_path,
        """\
        actions:
          - name: a
            kind: tool
            impl: tool_a
            description: {{ "x
            impl: ghost_tool
            y" | tojson }}
          - name: b
            kind: tool
            context_scope:
              seed_path: {{ pick(
                "$file:old.json",
                "$file:new.json") }}
        """,
    )

    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref == "tool_a"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_a`."]


def test_a_line_an_expression_changes_sets_no_value_from_its_words(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: judge
            kind: tool
            impl: tool_{{ 'x' }}
            schema: verdict{{ '_v2' }}
          - name: c
            kind: tool
            impl: tool_c
        """,
    )

    meta = build_index(tmp_path).file_actions[wf]["judge"]

    assert render_workflow_source(wf, tmp_path).data["actions"][0]["schema"] == "verdict_v2"
    assert meta.schema_ref != "verdict"
    assert meta.impl_ref != "tool_"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_c`."]


def test_the_fallback_location_of_an_action_is_not_in_a_dropped_branch(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
        {% if false %}
          - name: a
            impl: dropped_tool
        {% endif %}
        {% set block %}
          - name: a
            kind: tool
        {% endset %}
        {{ block }}
        """,
    )

    idx = build_index(tmp_path)

    assert set(idx.file_actions[wf]) == {"a"}
    assert idx.file_actions[wf]["a"].location.line != 2


_UP_THEN_A = "name: wf\nactions:\n  - name: up\n    impl: t\n  - name: a\n"


@pytest.mark.parametrize(
    ("body", "templates", "value", "kind"),
    [
        pytest.param(
            "    dependencies:\n      - up\n    context_scope:  {# fields the model reads #}\n"
            "      observe:\n        - up.title\n",
            {},
            "up.title",
            ReferenceType.CONTEXT_FIELD,
            id="comment-on-context-scope",
        ),
        pytest.param(
            "    context_scope:\n      observe:\n        - up.title\n"
            "    dependencies:  {# upstream actions #}\n      - up\n",
            {},
            "up",
            ReferenceType.ACTION,
            id="comment-on-dependencies",
        ),
        pytest.param(
            "    dependencies:\n      - up\n{% filter indent(4, first=True) %}\ncontext_scope:\n"
            "  observe:\n{% endfilter %}\n      - up.field\n",
            {},
            "up.field",
            ReferenceType.CONTEXT_FIELD,
            id="filter-outputs-keys",
        ),
        pytest.param(
            "    dependencies:\n      - up\n      {% call under() %}\n      - up.field\n"
            "      {% endcall %}\n",
            {
                "w.jinja2": "{% macro under() %}\n    context_scope:\n      observe:\n"
                "{{ caller() }}{% endmacro %}\n"
            },
            "up.field",
            ReferenceType.CONTEXT_FIELD,
            id="deep-call-outputs-keys",
        ),
    ],
)
def test_a_reference_has_the_type_of_the_key_the_render_puts_it_under(
    tmp_path, body, templates, value, kind
):
    head = "{% from 'w.jinja2' import under %}\n" if templates else ""
    wf = _project(tmp_path, head + _UP_THEN_A + body, templates)

    refs = build_index(tmp_path).references_by_file[wf]

    assert [r.type for r in refs if r.value == value] in ([], [kind])
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `t`."]


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(
            "    {{ 'notes' }}:\n      observe:\n        - ghost.y\n", id="at-scope-indent"
        ),
        pytest.param("      {{ 'notes' }}:\n        - ghost.y\n", id="at-list-indent"),
    ],
)
def test_an_expression_that_opens_a_key_ends_the_context_list(tmp_path, tail):
    wf = _project(
        tmp_path,
        _UP_THEN_A + "    context_scope:\n      observe:\n        - up.x\n" + tail,
    )

    assert _messages(wf, tmp_path) == ["Unresolved tool reference `t`."]


def test_the_last_of_a_repeated_actions_key_is_read(tmp_path):
    wf = _project(
        tmp_path,
        "name: wf\nactions:\n  - name: a\n    impl: old_tool\nactions:\n  - name: a\n    "
        "impl: new_tool\n",
    )

    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref == "new_tool"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `new_tool`."]


def test_an_action_with_no_mark_is_not_placed_on_a_schema_field_line(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set gen %}
          - name: summary
            impl: t_s
        {% endset %}
        name: wf
        actions:
          - name: other
            schema:
              fields:
                - name: summary
                  type: string
        {{ gen }}
        """,
    )

    idx = build_index(tmp_path)

    assert "summary" in idx.file_actions[wf]
    assert idx.file_actions[wf]["summary"].location.line != 9


def test_raw_text_with_braces_sets_no_value_from_its_words(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
        {% raw %}
            impl: tool_{{ x }}
        {% endraw %}
          - name: c
            kind: tool
            impl: tool_c
        """,
    )

    assert render_workflow_source(wf, tmp_path).data["actions"][0]["impl"] == "tool_{{ x }}"
    assert build_index(tmp_path).file_actions[wf]["a"].impl_ref != "tool_"
    assert _messages(wf, tmp_path) == ["Unresolved tool reference `tool_c`."]


def test_a_name_line_a_filter_renames_does_not_define_its_written_name(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro rename(old, new) %}{{ caller() | replace(old, new) }}{% endmacro %}
        name: wf
        actions:
          - name: old_name
            kind: tool
        {% call rename('old_name', 'new_name') %}
          - name: old_name
            kind: tool
        {% endcall %}
        """,
    )

    idx = build_index(tmp_path)

    assert [a["name"] for a in render_workflow_source(wf, tmp_path).data["actions"]] == [
        "old_name",
        "new_name",
    ]
    assert idx.duplicate_actions_by_file[wf] == set()
    assert idx.file_actions[wf]["old_name"].location.line == 3


def test_a_name_mark_moved_to_a_line_that_is_not_a_name_gives_no_source(tmp_path):
    wf = _project(
        tmp_path,
        "{% from 'my_steps.jinja2' import step %}\nname: wf\nactions:\n"
        "{{ step('x') | replace(':1:', ':3:') }}\n{{ step('ok') }}\n",
        {
            "my_steps.jinja2": "{% macro step(n) -%}\n- name: {{ n }}\n  kind: tool\n  "
            "impl: t\n{%- endmacro %}\n"
        },
    )

    r = render_workflow_source(wf, tmp_path)

    assert [a["name"] for a in r.data["actions"]] == ["x", "ok"]
    assert {name: loc.line for name, loc in r.action_sources.items()} == {"ok": 1}


def _ref_pairs(wf: Path, tmp_path: Path) -> set[tuple[str, str]]:
    return {(r.type.value, r.value) for r in build_index(tmp_path).references_by_file[wf]}


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(
            "    prompt: Summarize {{ source.topic }} in one line,\n      and keep it short.\n",
            id="starts-on-the-key-line",
        ),
        pytest.param(
            "    prompt:\n      Summarize {{ source.topic }} in one line,\n      and "
            "keep it short.\n",
            id="starts-on-the-next-line",
        ),
    ],
)
def test_a_multiline_plain_prompt_keeps_the_references_of_the_file(tmp_path, prompt):
    wf = _project(
        tmp_path,
        "actions:\n  - name: extract\n    kind: tool\n    impl: t1\n    schema: s1\n"
        "  - name: summarize\n" + prompt + "    schema: s2\n    dependencies: [extract]\n"
        "    context_scope:\n      observe:\n        - extract.x\n",
    )

    assert _ref_pairs(wf, tmp_path) == {
        ("tool", "t1"),
        ("schema", "s1"),
        ("schema", "s2"),
        ("action", "extract"),
        ("context_field", "extract.x"),
    }


def test_an_action_that_merges_a_name_keeps_its_own(tmp_path):
    wf = _project(
        tmp_path,
        """\
        actions:
          - &tpl
            name: base
            kind: tool
            impl: t1
          - name: derived
            <<: *tpl
            impl: t2
            schema: s2
            dependencies: [base]
          - name: last
            <<: *tpl
            dependencies:
              - derived
        """,
    )

    idx = build_index(tmp_path)

    assert idx.file_actions[wf]["derived"].impl_ref == "t2"
    assert {("tool", "t2"), ("schema", "s2"), ("action", "base"), ("action", "derived")} <= (
        _ref_pairs(wf, tmp_path)
    )


def test_a_yaml_error_line_counts_lines_as_the_editor_does(tmp_path):
    wf = _project(
        tmp_path,
        'name: wf\ndescription: "a b"\nactions:\n  - name: a\n    kind: tool\n'
        "  - name: b\n   bad: x\n",
    )

    error = build_index(tmp_path).parse_errors[wf]

    assert error.location.line == 6


def test_the_fallback_location_points_at_the_name_not_into_the_key(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% macro m() %}
        - name: q
        {% endmacro %}
        {% set x = m() %}
        name: wf
        actions:
        {% if x | trim == '- name: q' %}
          - name: a
            kind: tool
        {% else %}
          - name: b
            kind: tool
        {% endif %}
        """,
    )

    location = build_index(tmp_path).file_actions[wf]["a"].location

    assert (location.line, location.column) == (7, 10)


def test_words_in_a_block_scalar_give_no_reference_or_value(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
            prompt: $wf.real
            description: |
              prompt: $wf.fake
              impl: fake_tool
              schema: fake_schema
              dependencies: [ghost]
          - name: b
            kind: tool
            impl: >-
              real_tool
            # impl: comment_tool
        """,
    )

    idx = build_index(tmp_path)
    a, b = idx.file_actions[wf]["a"], idx.file_actions[wf]["b"]

    assert (a.prompt_ref, a.impl_ref, a.schema_ref) == ("wf.real", None, None)
    assert b.impl_ref is None
    assert {value for _, value in _ref_pairs(wf, tmp_path)} == {"wf.real"}


def test_raw_text_with_braces_sets_no_prompt_schema_or_seed_value(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
        {% raw %}
            prompt: $wf.p{{ x }}
            schema: verdict{{ x }}
            context_scope:
              seed_path: $file:old{{ v }}.json
        {% endraw %}
          - name: c
            kind: tool
            impl: tool_c
        """,
    )

    meta = build_index(tmp_path).file_actions[wf]["a"]

    assert meta.prompt_ref != "wf.p"
    assert meta.schema_ref != "verdict"
    assert _ref_pairs(wf, tmp_path) == {("tool", "tool_c")}


_VERSIONED = """\
actions:
  - name: up
    kind: tool
    prompt: "Say {{ source.text }}"
  - name: judge
    kind: tool
    dependencies: [up]
    versions: {param: i, range: [1, 3]}
"""


@pytest.mark.parametrize(
    "line, key, expected",
    [
        pytest.param(
            "guard: {condition: 'up.score > {{ i }}'}",
            "guard",
            {"condition": "up.score > {{ i }}"},
            id="guard",
        ),
        pytest.param(
            'output_field: "out_{{ i }}"', "output_field", "out_{{ i }}", id="output-field"
        ),
    ],
)
def test_a_value_that_reads_a_version_variable_shows_its_written_text(
    tmp_path, line, key, expected
):
    wf = _project(tmp_path, f"{_VERSIONED}    {line}\n")

    rendered = render_workflow_source(wf, tmp_path)

    assert rendered.data["actions"][1][key] == expected
    assert not [c for c in repr(rendered.data) if "" <= c <= ""]
    judge = build_index(tmp_path).file_actions[wf]["judge"]
    if key == "guard":
        assert judge.guard_condition == "up.score > {{ i }}"
        assert judge.guard_line == 8
    else:
        assert judge.output_field == "out_{{ i }}"


def test_the_text_for_the_tree_holds_each_version_value_as_written(tmp_path):
    lines = "    dependencies: [\"up_{{ i }}\"]\n    guard: {condition: 'up.score > {{ i }}'}\n"
    wf = _project(tmp_path, _VERSIONED + lines)

    rendered = render_workflow_source(wf, tmp_path)

    judge = yaml.safe_load(rendered.text)["actions"][1]
    assert judge["dependencies"] == ["up_{{ i }}"]
    assert judge["guard"] == {"condition": "up.score > {{ i }}"}
    assert len(rendered.text.splitlines()) == len(textwrap.dedent(_VERSIONED).splitlines()) + 2


@pytest.mark.parametrize(
    "lines, condition",
    [
        pytest.param('    guard: &g "up.x > {{ i }}"\n', "up.x > {{ i }}", id="anchor"),
        pytest.param("    guard: >-\n      up.x > {{ i }}\n", "up.x > {{ i }}", id="folded"),
        pytest.param("    guard: {{ i }} < up.x  # later\n", "{{ i }} < up.x", id="comment"),
        pytest.param(
            "    guard: {{ i }} < up.x {# why #}\n", "{{ i }} < up.x", id="jinja-comment"
        ),
        pytest.param(
            "    guard: {{ i }} < up.x and up.s == it's  # later\n",
            "{{ i }} < up.x and up.s == it's",
            id="apostrophe",
        ),
        pytest.param("    guard: {{ i }} == 'a #b'\n", "{{ i }} == 'a", id="quote-in-plain-text"),
    ],
)
def test_a_guard_that_reads_a_version_variable_keeps_its_line_and_drops_its_comment(
    tmp_path, lines, condition
):
    wf = _project(tmp_path, _VERSIONED + lines)

    idx = build_index(tmp_path)

    judge = idx.file_actions[wf]["judge"]
    assert (judge.guard_line, judge.guard_condition) == (8, condition)
    assert not [m for m in _messages(wf, tmp_path) if "`later`" in m or "`why`" in m]


@pytest.mark.parametrize(
    "lines, key, expected",
    [
        pytest.param(
            "    guard: {{ i }} < up.x\n      and up.y > 1\n",
            "guard",
            "{{ i }} < up.x and up.y > 1",
            id="multi-line-plain",
        ),
        pytest.param(
            "    guard: {{ i }} < up.x  # see {{ i }}\n",
            "guard",
            "{{ i }} < up.x",
            id="tag-in-comment",
        ),
        pytest.param(
            "    schema: {score_{{ i }}: number, other: string}\n",
            "schema",
            {"score_{{ i }}": "number", "other": "string"},
            id="flow-key",
        ),
        pytest.param(
            "    schema:\n      {{ 'score' }}_{{ i }}: number\n",
            "schema",
            {"{{ 'score' }}_{{ i }}": "number"},
            id="block-key",
        ),
        pytest.param(
            "    dependencies: [{{ 'up' }}_{{ i }}]\n",
            "dependencies",
            ["{{ 'up' }}_{{ i }}"],
            id="list",
        ),
        pytest.param(
            "    schema: {a: {b_{{ i }}: {{ 'x' }}}}\n",
            "schema",
            {"a": {"b_{{ i }}": "{{ 'x' }}"}},
            id="nested-key",
        ),
    ],
)
def test_a_version_value_that_starts_with_a_tag_is_read_as_agac_reads_it(
    tmp_path, lines, key, expected
):
    wf = _project(tmp_path, _VERSIONED + lines)

    rendered = render_workflow_source(wf, tmp_path)

    assert rendered.data["actions"][1][key] == expected
    assert yaml.safe_load(rendered.text) == rendered.data


def test_the_text_for_the_tree_escapes_a_character_yaml_does_not_take_as_written(tmp_path):
    written = '"o\\x7f\\x85\\x9f\\u2028\\uffff\\U0001F600{{ i }}"'
    wf = _project(tmp_path, f"{_VERSIONED}    output_field: {written}\n")

    rendered = render_workflow_source(wf, tmp_path)

    assert (
        rendered.data["actions"][1]["output_field"] == "o\x7f\x85\x9f\u2028\uffff\U0001f600{{ i }}"
    )
    assert yaml.safe_load(rendered.text) == rendered.data


def test_a_line_of_an_action_named_with_a_version_variable_is_owned_by_its_written_name(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% set k = 'tool' %}
        actions:
          - name: up
            kind: {{ k }}
          - name: "v_{{ i }}"
            kind: tool
            dependencies: [up]
            versions: {param: i, range: [1, 3]}
        """,
    )

    rendered = render_workflow_source(wf, tmp_path)

    assert rendered.line_owners[5] == "v_{{ i }}"
    assert rendered.line_owners[6] == "v_{{ i }}"


def _second_workflow(tmp_path: Path, workflow: str) -> Path:
    config = tmp_path / "agent_workflow" / "wf2" / "agent_config"
    config.mkdir(parents=True)
    wf = config / "wf2.yml"
    wf.write_text(textwrap.dedent(workflow))
    return wf


_BROKEN_TEMPLATES = {"bad.jinja2": "{% macro m( %}\n{% endmacro %}\n"}


def test_a_workflow_with_no_tag_is_read_as_yaml_when_the_templates_do_not_load(tmp_path):
    wf = _project(
        tmp_path,
        """\
        name: wf
        actions:
          - name: a
            kind: tool
          - name: b
            kind: tool
            dependencies: [a, missing]
        """,
        _BROKEN_TEMPLATES,
    )

    idx = build_index(tmp_path)

    assert wf not in idx.parse_errors
    assert set(idx.file_actions[wf]) == {"a", "b"}
    assert idx.file_actions[wf]["b"].location.line == 4
    assert _messages(wf, tmp_path) == ["Unresolved action reference `missing`."]
    sources = render_workflow_source(wf, tmp_path).action_sources
    assert {name: (loc.line, loc.column) for name, loc in sources.items()} == {
        "a": (2, 10),
        "b": (4, 10),
    }


@pytest.mark.parametrize(
    "workflow, renders",
    [
        pytest.param("actions:\n  - name: a\n    kind: tool\n", True, id="no-tag"),
        pytest.param(
            "# {% set k = 1 %}\nactions:\n  - name: a\n    kind: tool\n", False, id="tag"
        ),
    ],
)
def test_a_templates_path_that_is_a_file_fails_only_a_workflow_with_a_tag(
    tmp_path, workflow, renders
):
    wf = _project_without_templates_folder(tmp_path, workflow)
    (tmp_path / "templates").write_text("not a folder\n")

    idx = build_index(tmp_path)

    if renders:
        assert set(idx.file_actions[wf]) == {"a"}
        assert wf not in idx.parse_errors
    else:
        assert idx.file_actions[wf] == {}
        assert _messages(wf, tmp_path)[0].startswith("Workflow does not render: ")


@pytest.mark.parametrize(
    "tag_line",
    [
        pytest.param("description: \"{{ 'x' }}\"", id="expression"),
        pytest.param("# {% set k = 1 %}", id="statement"),
        pytest.param("# {# a note #}", id="comment"),
    ],
)
def test_a_workflow_with_a_tag_does_not_render_when_the_templates_do_not_load(tmp_path, tag_line):
    _project(tmp_path, "name: wf\nactions:\n  - name: a\n    kind: tool\n", _BROKEN_TEMPLATES)
    wf = _second_workflow(tmp_path, f"{tag_line}\nactions:\n  - name: c\n    kind: tool\n")

    idx = build_index(tmp_path)

    assert wf in idx.parse_errors
    assert idx.file_actions[wf] == {}
    messages = _messages(wf, tmp_path)
    assert len(messages) == 1
    assert messages[0].startswith("Workflow does not render: ")


def test_the_editor_reads_the_actions_that_agac_loads(tmp_path):
    wf = _project(
        tmp_path,
        """\
        {% from 'steps.jinja2' import step %}
        {% set fast = true %}
        {% set kind = 'tool' %}
        name: wf
        actions:
          {{ step('extract') | indent(2) }}
        {% if fast %}
          - name: summarize
            kind: {{ kind }}
            dependencies: [extract]
        {% else %}
          - name: slow
            kind: tool
        {% endif %}
          - name: publish
            kind: tool
            dependencies: [summarize]
        """,
        {"steps.jinja2": "{% macro step(n) %}\n- name: {{ n }}\n  kind: tool\n{% endmacro %}\n"},
    )

    rendered = render_workflow_source(wf, tmp_path)
    loaded = yaml.safe_load(
        render_pipeline_with_templates(
            wf, tmp_path / "templates", compile_schemas=False, project_root=tmp_path
        )
    )

    names = [action["name"] for action in rendered.data["actions"]]
    assert names == [action["name"] for action in loaded["actions"]]
    assert names == ["extract", "summarize", "publish"]
