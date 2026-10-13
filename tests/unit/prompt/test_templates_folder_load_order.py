"""What a templates/ file reads from another does not depend on what the files are called."""

import logging
from pathlib import Path

import pytest
import yaml

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates

# Each pair names the file that defines a name before and after the file that reads it.
BEFORE_AND_AFTER = pytest.mark.parametrize("definer", ["a_defs.j2", "z_defs.j2"])


def _load(tmp_path: Path, workflow: str, templates: dict[str, str]) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir()
    for name, text in templates.items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def _workflow(prompt: str) -> str:
    return f"""\
name: wf
actions:
  - name: summarize
    intent: "Summarize"
    prompt: "{prompt}"
"""


STD_ACTION = """\
{% macro std_action(n) %}
- name: {{ n }}
  intent: "Summarize"
  prompt: "Summarize the page in {{ house_length() }}."
{% endmacro %}
"""

MACRO_WORKFLOW = """\
{% from 'm_common.j2' import std_action %}
name: wf
actions:
  {{ std_action('summarize') | indent(2) }}
"""


@BEFORE_AND_AFTER
def test_a_macro_calls_another_files_macro(tmp_path, definer):
    data = _load(
        tmp_path,
        MACRO_WORKFLOW,
        {
            "m_common.j2": STD_ACTION,
            definer: "{% macro house_length() %}two sentences{% endmacro %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "Summarize the page in two sentences."


@BEFORE_AND_AFTER
def test_an_include_without_context_reads_another_files_variable(tmp_path, definer):
    data = _load(
        tmp_path,
        _workflow("{% include 'm_partial.j2' without context %} Summarize the page."),
        {
            "m_partial.j2": "Write in a {{ house_style }} tone.",
            definer: "{% set house_style = 'formal' %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "Write in a formal tone. Summarize the page."


@BEFORE_AND_AFTER
def test_an_import_without_context_reads_another_files_variable(tmp_path, definer):
    data = _load(
        tmp_path,
        "{% from 'm_tone.j2' import tone %}\n" + _workflow("Write in a {{ tone }} tone."),
        {
            "m_tone.j2": "{% set tone = house_style | upper %}\n",
            definer: "{% set house_style = 'formal' %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "Write in a FORMAL tone."


@BEFORE_AND_AFTER
def test_a_files_top_level_calls_another_files_macro(tmp_path, definer):
    data = _load(
        tmp_path,
        _workflow("Summarize the page in {{ length }}."),
        {
            "m_length.j2": "{% set length = house_length() %}\n",
            definer: "{% macro house_length() %}two sentences{% endmacro %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "Summarize the page in two sentences."


@pytest.mark.parametrize(
    "first, second, third",
    [("a.j2", "b.j2", "c.j2"), ("c.j2", "b.j2", "a.j2"), ("b.j2", "c.j2", "a.j2")],
)
def test_a_variable_built_from_a_variable_built_from_a_third_files(tmp_path, first, second, third):
    data = _load(
        tmp_path,
        _workflow("{{ greeting }}"),
        {
            first: "{% set greeting = tone ~ '!' %}\n",
            second: "{% set tone = style | upper %}\n",
            third: "{% set style = 'formal' %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "FORMAL!"


@pytest.mark.parametrize(
    "first, second, third",
    [("a.j2", "b.j2", "c.j2"), ("c.j2", "b.j2", "a.j2"), ("b.j2", "c.j2", "a.j2")],
)
def test_macros_call_through_three_files_and_back(tmp_path, first, second, third):
    data = _load(
        tmp_path,
        _workflow("{{ outer() }}"),
        {
            first: "{% macro outer() %}[{{ middle() }}]{% endmacro %}\n"
            "{% macro word() %}formal{% endmacro %}\n",
            second: "{% macro middle() %}<{{ inner() }}>{% endmacro %}\n",
            third: "{% macro inner() %}{{ word() }}{% endmacro %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "[<formal>]"


@pytest.mark.parametrize("reader", ["a_common.j2", "m_common.j2", "z_common.j2"])
def test_a_name_two_files_define_is_the_later_named_files_everywhere(tmp_path, reader, caplog):
    workflow = MACRO_WORKFLOW.replace("m_common.j2", reader)
    with caplog.at_level(logging.WARNING):
        data = _load(
            tmp_path,
            workflow + '  - name: direct\n    intent: x\n    prompt: "{{ house_length() }}"\n',
            {
                reader: STD_ACTION,
                "base.j2": "{% macro house_length() %}two sentences{% endmacro %}\n",
                "helpers.j2": "{% macro house_length() %}one sentence{% endmacro %}\n",
            },
        )

    prompts = {action["name"]: action["prompt"] for action in data["actions"]}
    assert prompts == {
        "summarize": "Summarize the page in one sentence.",
        "direct": "one sentence",
    }
    warnings = [r.getMessage() for r in caplog.records if "redefines global name" in r.getMessage()]
    assert len(warnings) == 1
    assert "'helpers.j2'" in warnings[0] and "house_length" in warnings[0]


def test_a_files_own_macro_is_the_one_its_macros_call(tmp_path):
    data = _load(
        tmp_path,
        _workflow("{{ outer() }} / {{ word() }}"),
        {
            "a.j2": "{% macro word() %}mine{% endmacro %}\n"
            "{% macro outer() %}{{ word() }}{% endmacro %}\n",
            "z.j2": "{% macro word() %}theirs{% endmacro %}\n",
        },
    )

    assert data["actions"][0]["prompt"] == "mine / theirs"


@pytest.mark.parametrize("reader", ["a_common.j2", "z_common.j2"])
def test_a_macro_calling_a_name_no_file_defines_fails_the_load(tmp_path, reader):
    with pytest.raises(TemplateRenderingError, match="'house_length' is undefined"):
        _load(
            tmp_path,
            MACRO_WORKFLOW.replace("m_common.j2", reader),
            {reader: STD_ACTION, "m_other.j2": "{% set house_style = 'formal' %}\n"},
        )


@pytest.mark.parametrize("reader", ["a_length.j2", "z_length.j2"])
def test_a_top_level_call_of_a_name_no_file_defines_fails_naming_the_file(tmp_path, reader):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            _workflow("x"),
            {
                reader: "{% set length = house_length() %}\n",
                "m_other.j2": "{% set house_style = 'formal' %}\n",
            },
        )

    assert reader in str(raised.value)
    assert "'house_length' is undefined" in str(raised.value)


def test_a_variable_a_file_stops_setting_is_not_left_behind(tmp_path):
    with pytest.raises(TemplateRenderingError, match="'extra' is undefined"):
        _load(
            tmp_path,
            _workflow("{{ extra }}"),
            {
                "a.j2": "{% if not flag %}{% set extra = 'stale' %}{% endif %}\n",
                "z.j2": "{% set flag = true %}\n",
            },
        )
