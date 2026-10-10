"""Loading a workflow renders only what the load can resolve.

A name a workflow file defines (`{% set %}`, a macro, `load_prompt`, a loop variable) is
rendered when the file loads. A name only a version or a record supplies is left for the
stage that has it: a `prompt:` renders per record, a versioned action's other values per
version. A name no stage supplies fails the load instead of rendering as nothing.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _load(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    for name, text in (templates or {}).items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def _actions(data: dict) -> dict[str, dict]:
    return {action["name"]: action for action in data["actions"]}


# ── per-record and per-version names reach the prompt ────────────────────


def test_a_version_variable_in_an_inline_prompt_is_left_for_each_version(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
  - name: extract
    versions: {range: [1, 3]}
    prompt: |
      Extract questions using strategy {{ i }}
    intent: "Extract"
""",
    )

    for action in data["actions"]:
        assert action["prompt"] == "Extract questions using strategy {{ i }}\n"


def test_an_upstream_field_in_an_inline_prompt_is_left_for_each_record(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
  - name: simple_validate
    prompt: |
      Validate these facts: {{ extract_facts.facts }}
      {% for fact in extract_facts.list %}- {{ fact.text | upper }}{% endfor %}
      {% if version.first %}first{% endif %}{{ source.note | default("N/A") }}
    intent: "Validate"
""",
    )

    assert _actions(data)["simple_validate"]["prompt"] == (
        "Validate these facts: {{ extract_facts.facts }}\n"
        "{% for fact in extract_facts.list %}- {{ fact.text | upper }}{% endfor %}\n"
        '{% if version.first %}first{% endif %}{{ source.note | default("N/A") }}\n'
    )


def test_a_quoted_or_plain_inline_prompt_keeps_its_template(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
  - name: a
    prompt: "You are classifier {{ classifier_id }} (also {{ i }})."
  - name: b
    prompt: Summarise {{ source.text }}
""",
    )

    actions = _actions(data)
    assert actions["a"]["prompt"] == "You are classifier {{ classifier_id }} (also {{ i }})."
    assert actions["b"]["prompt"] == "Summarise {{ source.text }}"


def test_a_raw_block_still_hands_its_body_to_the_prompt(tmp_path):
    """The workaround people used before: its text reaches the prompt as it did."""
    data = _load(
        tmp_path,
        """\
actions:
  - name: a
    prompt: |
      {% raw %}Validate these facts: {{ extract_facts.facts }}{% endraw %}
    intent: "Validate"
""",
    )

    assert _actions(data)["a"]["prompt"] == "Validate these facts: {{ extract_facts.facts }}\n"


# ── what the load resolves still renders at load ──────────────────────────


def test_a_set_variable_renders_at_load_beside_a_per_record_name(tmp_path):
    data = _load(
        tmp_path,
        """\
{% set tone = "formal" %}
{% set model = "gpt-4o-mini" %}
defaults:
  model_name: {{ model }}
actions:
  - name: write
    prompt: "Write in a {{ tone }} tone about {{ source.topic }}."
""",
    )

    assert data["defaults"]["model_name"] == "gpt-4o-mini"
    assert _actions(data)["write"]["prompt"] == "Write in a formal tone about {{ source.topic }}."


def test_a_template_macro_and_load_prompt_render_at_load(tmp_path):
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "common.md").write_text(
        "{prompt Header}\nHEADER for {{ source.title }}\n{end_prompt}\n"
    )
    data = _load(
        tmp_path,
        """\
{% from 'chain.jinja2' import chain %}
actions:
  - name: first
    prompt: |
      {{ load_prompt("common.Header") }}
      Body: {{ source.text }}
{{ chain('first') | indent(2, first=True) }}
""",
        templates={
            "chain.jinja2": """\
{% macro chain(dep) -%}
- name: check_{{ dep }}
  dependencies: [{{ dep }}]
  prompt: "Check {{ dep }}: {{ first.answer }}"
{%- endmacro %}
""",
        },
    )

    actions = _actions(data)
    assert actions["first"]["prompt"] == "HEADER for {{ source.title }}\nBody: {{ source.text }}\n"
    assert actions["check_first"]["dependencies"] == ["first"]
    assert actions["check_first"]["prompt"] == "Check first: {{ first.answer }}"


def test_a_loop_generating_actions_renders_its_variable_at_load(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
{% for stage in [1, 2] %}
  - name: stage_{{ stage }}
    intent: "Process stage {{ stage }}"
    prompt: "Stage {{ stage }} of {{ source.text }}"
{% endfor %}
""",
    )

    actions = _actions(data)
    assert actions["stage_2"]["intent"] == "Process stage 2"
    assert actions["stage_2"]["prompt"] == "Stage 2 of {{ source.text }}"


def test_a_defined_test_and_a_default_still_resolve_at_load(tmp_path):
    data = _load(
        tmp_path,
        """\
defaults:
  model_name: "{{ model | default('gpt-4o-mini') }}"
actions:
  - name: a
    prompt: "x"
{% if enable_validation is defined %}
  - name: validate
    prompt: "y"
{% endif %}
""",
    )

    assert data["defaults"]["model_name"] == "gpt-4o-mini"
    assert list(_actions(data)) == ["a"]


# ── a versioned action's other values render per version ──────────────────


def test_a_setting_that_branches_on_the_version_renders_per_version(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
  - name: model_comparison
    versions:
      range: [1, 3]
    model_vendor: "{% if i == 1 %}openai{% elif i == 2 %}anthropic{% else %}gemini{% endif %}"
    intent: "Version {{ version.i }} of {{ version.length }}"
    prompt: "Compare {{ i }}"
""",
    )

    vendors = [action["model_vendor"] for action in data["actions"]]
    assert vendors == ["openai", "anthropic", "gemini"]
    assert data["actions"][2]["intent"] == "Version 3 of 3"
    assert data["actions"][0]["prompt"] == "Compare {{ i }}"


# ── a name nothing supplies fails the load ────────────────────────────────


@pytest.mark.parametrize(
    "workflow, name",
    [
        pytest.param(
            'defaults:\n  model_name: "{{ modle }}"\nactions: []\n', "modle", id="setting"
        ),
        pytest.param(
            'actions:\n  - name: a\n    intent: "About {{ source.topic }}"\n',
            "source",
            id="per-record-name-outside-a-prompt",
        ),
        pytest.param(
            'actions:\n  - name: a\n    model_vendor: "{% if i == 1 %}openai{% endif %}"\n',
            "i",
            id="version-name-on-an-unversioned-action",
        ),
        pytest.param(
            'actions:\n  - name: a\n    prompt: "x"\n'
            "{% if enable_validation %}\n  - name: v\n    prompt: y\n{% endif %}\n",
            "enable_validation",
            id="structural-condition",
        ),
    ],
)
def test_a_name_nothing_supplies_fails_the_load(tmp_path, workflow, name):
    with pytest.raises((ConfigurationError, TemplateRenderingError)) as raised:
        _load(tmp_path, workflow)

    assert f"'{name}'" in str(raised.value)


def test_a_missing_attribute_of_a_load_time_name_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError, match="has no attribute 'b'"):
        _load(
            tmp_path,
            "{% set cfg = {'a': 1} %}\ndefaults:\n  model_name: \"{{ cfg.b }}\"\nactions: []\n",
        )


def test_a_variable_a_prompt_assigns_per_record_is_left_with_every_read(tmp_path):
    """Set at load and reassigned per record, a value the load read would be frozen."""
    prompt = (
        "{% set ns = namespace(n=0) %}"
        "{% for f in extract.facts %}{% set ns.n = ns.n + 1 %}{% endfor %}"
        "Count: {{ ns.n }}\n"
        '{% set tone = "plain" %}'
        '{% if version.first %}{% set tone = "careful" %}{% endif %}'
        "Be {{ tone }}.\n"
    )
    data = _load(
        tmp_path,
        "actions:\n  - name: count\n    prompt: |\n"
        + "".join(f"      {line}\n" for line in prompt.splitlines())
        + '    intent: "Count"\n',
    )

    assert _actions(data)["count"]["prompt"] == prompt


# ── a value the load captures around a per-record tag ─────────────────────


def _block(prompt: str) -> str:
    return "".join(f"      {line}\n" for line in prompt.splitlines())


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(
            "{% set kind %}{{ source.page_content }}{% endset %}\n"
            '{% if kind == "urgent" %}ESCALATE NOW.{% else %}Handle normally.{% endif %}'
            " Kind={{ kind }} len={{ kind | length }}",
            id="set-block",
        ),
        pytest.param(
            "{% macro kind() %}{{ source.page_content }}{% endmacro %}"
            '{% if kind() == "urgent" %}ESCALATE{% else %}normal{% endif %}'
            " {{ kind() }} {{ kind() | length }}",
            id="macro",
        ),
        pytest.param(
            "{% filter upper %}{{ source.page_content }}{% endfilter %}",
            id="filter-block",
        ),
        pytest.param(
            "{% set facts %}{% for f in extract.facts %}{{ f }}{% endfor %}{% endset %}"
            "{% set n = facts | length %}{% if n > 3 %}long{% endif %} {{ facts }}",
            id="set-block-over-a-loop-and-a-variable-it-feeds",
        ),
    ],
)
def test_a_prompt_that_tests_a_value_it_captures_per_record_keeps_it_whole(tmp_path, prompt):
    """Decided at load, the test reads the tag's text and every record gets one branch."""
    data = _load(
        tmp_path,
        "actions:\n  - name: a\n    prompt: |\n" + _block(prompt) + '    intent: "Triage"\n',
    )

    assert _actions(data)["a"]["prompt"] == prompt + "\n"


def test_a_value_captured_per_record_and_only_output_carries_its_tag_into_the_prompt(tmp_path):
    """Output whole, a set block or macro of the file hands its per-record tag on."""
    data = _load(
        tmp_path,
        """\
{% set header %}Title: {{ source.title }}{% endset %}
{% macro stage(n) %}
  - name: stage_{{ n }}
    prompt: "Stage {{ n }} of {{ source.text }}"
{% endmacro %}
actions:
  - name: write
    prompt: "{{ header }}. Body."
{{ stage(1) }}
""",
    )

    actions = _actions(data)
    assert actions["write"]["prompt"] == "Title: {{ source.title }}. Body."
    assert actions["stage_1"]["prompt"] == "Stage 1 of {{ source.text }}"


def test_a_prompt_testing_a_value_the_file_captures_outside_it_fails_the_load(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        _load(
            tmp_path,
            """\
{% macro kind() %}{{ source.page_content }}{% endmacro %}
actions:
  - name: a
    prompt: |
      {% if kind() == "urgent" %}ESCALATE{% else %}normal{% endif %}
""",
        )

    assert "'kind'" in str(raised.value)


def test_a_prompt_testing_a_templates_macro_that_renders_a_record_tag_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            'actions:\n  - name: a\n    prompt: |\n      {% if kind() == "urgent" %}E{% endif %}\n',
            templates={"kinds.j2": "{% macro kind() %}{{ source.page_content }}{% endmacro %}"},
        )

    assert "'kind'" in str(raised.value)


def test_a_templates_macro_captured_in_the_prompt_can_be_tested_per_record(tmp_path):
    """What the load error suggests: the capture waits for the record with its test."""
    data = _load(
        tmp_path,
        "actions:\n  - name: a\n    prompt: |\n"
        + _block('{% set k %}{{ kind() }}{% endset %}{% if k == "urgent" %}E{% endif %}')
        + '    intent: "Triage"\n',
        templates={"kinds.j2": "{% macro kind() %}{{ source.page_content }}{% endmacro %}"},
    )

    assert _actions(data)["a"]["prompt"] == (
        '{% set k %}{{ source.page_content }}{% endset %}{% if k == "urgent" %}E{% endif %}\n'
    )


def test_a_variable_a_prompt_loop_sets_is_not_the_one_a_load_time_loop_sets(tmp_path):
    """A set inside a loop binds only in that loop, so the two never meet."""
    data = _load(
        tmp_path,
        """\
actions:
{% for stage in [1, 2] %}{% set label = "Stage " ~ stage %}
  - name: s{{ stage }}
    intent: "{{ label }}"
    prompt: "{% for item in source.items %}{% set label = item.name %}- {{ label }}{% endfor %}"
{% endfor %}
""",
    )

    actions = _actions(data)
    assert actions["s2"]["intent"] == "Stage 2"
    assert actions["s2"]["prompt"] == (
        "{% for item in source.items %}{% set label = item.name %}- {{ label }}{% endfor %}"
    )


def test_a_templates_file_uses_another_files_macro_beside_a_per_record_tag(tmp_path):
    """templates/ files read each other's exports whichever of them loads first."""
    data = _load(
        tmp_path,
        """\
actions:
  - name: a
    prompt: "{{ wrap('x') }} {{ source.text }}"
""",
        templates={
            "a_wrap.j2": "{% macro wrap(v) %}[{{ helper(v) }}]{% endmacro %}",
            "b_helper.j2": "{% macro helper(v) %}<{{ v }}>{% endmacro %}",
        },
    )

    assert _actions(data)["a"]["prompt"] == "[<x>] {{ source.text }}"


# ── an included template reads what its includer binds ───────────────────


def test_an_included_template_reads_a_variable_the_workflow_sets(tmp_path):
    data = _load(
        tmp_path,
        """\
{% set model = "gpt-4o-mini" %}
{% include 'defaults.j2' %}
actions:
  - name: a
    prompt: "Summarise {{ source.text }}"
""",
        templates={"defaults.j2": 'defaults:\n  model_name: "{{ model }}"\n'},
    )

    assert data["defaults"]["model_name"] == "gpt-4o-mini"


def test_an_included_partial_reads_the_loop_variable_and_keeps_its_record_tags(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
{% for s in ["a", "b"] %}
{% include 'action.j2' %}
{% endfor %}
""",
        templates={
            "action.j2": '  - name: act_{{ s }}\n    prompt: "{{ s }}: {{ source.text }}"\n'
        },
    )

    assert _actions(data)["act_b"]["prompt"] == "b: {{ source.text }}"


def test_a_value_captured_around_an_include_of_a_record_tag_waits_for_the_record(tmp_path):
    data = _load(
        tmp_path,
        "actions:\n  - name: a\n    prompt: |\n"
        + _block("{% set k %}{% include 'kind.j2' %}{% endset %}{% if k == 'u' %}E{% endif %}")
        + '    intent: "Triage"\n',
        templates={"kind.j2": "{{ source.page_content }}"},
    )

    assert _actions(data)["a"]["prompt"] == (
        "{% set k %}{{ source.page_content }}{% endset %}{% if k == 'u' %}E{% endif %}\n"
    )


# ── a YAML error names left tags only when they caused it ─────────────────


def test_a_yaml_typo_beside_a_per_record_prompt_gets_no_template_note(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        _load(
            tmp_path,
            'actions:\n  - name: a\n    prompt: "Summarise {{ source.text }}"\n   intent: x\n',
        )

    message = str(raised.value)
    assert "'source'" not in message
    assert "left in place" not in message


def test_a_yaml_error_from_a_left_condition_names_only_that_condition(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        _load(
            tmp_path,
            "actions:\n"
            '  - name: write\n    prompt: "Summarise {{ source.text }}"\n'
            "{% if enable_validation %}\n  - name: v\n    prompt: y\n{% endif %}\n",
        )

    message = str(raised.value)
    assert "'enable_validation'" in message
    assert "'source'" not in message
    assert "'write'" not in message


def test_a_yaml_error_from_a_definition_a_prompt_tests_names_it(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        _load(
            tmp_path,
            '{% set tone = "plain" %}\nactions:\n  - name: a\n    prompt: |\n'
            '      {% if version.first %}{% set tone = "careful" %}{% endif %}Be {{ tone }}.\n'
            '    intent: "x"\n',
        )

    message = str(raised.value)
    assert "'tone'" in message
    assert "'version'" not in message
