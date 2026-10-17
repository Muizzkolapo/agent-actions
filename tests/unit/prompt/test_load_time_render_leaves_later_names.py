"""Loading a workflow renders only what the load can resolve.

A name a workflow file defines (`{% set %}`, a macro, `load_prompt`, a loop variable) is
rendered when the file loads. A prompt that reads a name only a record supplies is left
whole for the per-record render, and a versioned action's value that reads a version
variable renders per version. A name no stage supplies fails the load instead of
rendering as nothing.
"""

import json
from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService


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


# ── a prompt that renders per record keeps every tag of its own ───────────


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
        "actions:\n  - name: extract\n    kind: tool\n"
        "  - name: a\n    prompt: |\n" + _block(prompt) + '    intent: "Triage"\n',
    )

    assert _actions(data)["a"]["prompt"] == prompt + "\n"


def test_a_load_time_variable_a_prompt_reassigns_per_record_starts_from_its_load_value(
    tmp_path,
):
    data = _load(
        tmp_path,
        '{% set tone = "plain" %}\nactions:\n  - name: a\n    prompt: |\n'
        '      {% if version.first %}{% set tone = "careful" %}{% endif %}Be {{ tone }}.\n'
        '    intent: "x"\n',
    )
    prompt = _actions(data)["a"]["prompt"]

    assert prompt.startswith('{% set tone = "plain" +%}')
    render = PromptPreparationService._render_prompt_template
    assert render(prompt, {"version": {"first": True}}) == "Be careful.\n"
    assert render(prompt, {"version": {"first": False}}) == "Be plain.\n"


def test_load_time_data_a_prompt_reads_inside_a_block_is_set_at_its_top(tmp_path):
    data = _load(
        tmp_path,
        '{% set fields = ["title", "body"] %}\nactions:\n  - name: a\n    prompt: |\n'
        "      {% for f in fields %}{{ f }}: {{ source[f] }}\n      {% endfor %}\n",
    )
    prompt = _actions(data)["a"]["prompt"]

    assert prompt.startswith('{% set fields = ["title", "body"] +%}')
    record = {"source": {"title": "T", "body": "B"}}
    assert PromptPreparationService._render_prompt_template(prompt, record) == (
        "title: T\nbody: B\n"
    )


def test_a_macro_writing_actions_gives_them_per_record_prompts(tmp_path):
    data = _load(
        tmp_path,
        """\
{% macro stage(n) %}
  - name: stage_{{ n }}
    prompt: "Stage {{ n }} of {{ source.text }}"
{% endmacro %}
actions:
{{ stage(1) }}
{{ stage(2) }}
""",
    )

    assert _actions(data)["stage_2"]["prompt"] == "Stage 2 of {{ source.text }}"


@pytest.mark.parametrize(
    "workflow",
    [
        pytest.param(
            "{% set header %}Title: {{ source.title }}{% endset %}\nactions:\n  - name: a\n"
            '    prompt: "{{ header }}. Body."\n',
            id="set-block-outside-the-prompt",
        ),
        pytest.param(
            "{% macro kind() %}{{ source.page_content }}{% endmacro %}\nactions:\n"
            '  - name: a\n    prompt: |\n      {% if kind() == "urgent" %}E{% endif %}\n',
            id="macro-outside-the-prompt",
        ),
        pytest.param(
            '{% macro wrap(name) %}\n  - name: {{ name }}\n    prompt: "{{ caller() }}"\n'
            "{%- endmacro %}\nactions:\n{% call wrap('a') %}Do {{ source.x }}{% endcall %}\n",
            id="caller-of-a-macro-writing-actions",
        ),
    ],
)
def test_a_per_record_tag_the_file_renders_outside_a_prompt_fails_the_load(tmp_path, workflow):
    """The load renders it, where `source` does not exist; the error says why."""
    with pytest.raises(TemplateRenderingError) as raised:
        _load(tmp_path, workflow)

    message = str(raised.value)
    assert "'source' is undefined" in message
    assert "only an action's prompt renders per record" in message


def test_a_raw_block_hands_a_macros_per_record_tag_to_the_prompt(tmp_path):
    data = _load(
        tmp_path,
        "{% macro kind() %}{% raw %}{{ source.page_content }}{% endraw %}{% endmacro %}\n"
        'actions:\n  - name: a\n    prompt: "Kind: {{ kind() }} of {{ source.page_id }}"\n',
    )

    assert (
        _actions(data)["a"]["prompt"] == "Kind: {{ source.page_content }} of {{ source.page_id }}"
    )


@pytest.mark.parametrize(
    "prompt, name",
    [
        pytest.param(
            '{% if kind() == "urgent" %}E{% endif %} {{ source.page_id }}', "kind", id="macro"
        ),
        pytest.param(
            "{% if source.x %}{{ load_prompt('p.P') }}{% endif %}", "load_prompt", id="load-prompt"
        ),
    ],
)
def test_a_per_record_prompt_using_a_load_time_function_in_a_block_fails_the_load(
    tmp_path, prompt, name
):
    """Only data reaches the per-record render; the error names what does not."""
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            "actions:\n  - name: a\n    prompt: |\n" + _block(prompt),
            templates={"kinds.j2": "{% macro kind() %}k{% endmacro %}"},
        )

    message = str(raised.value)
    assert f"'{name}'" in message
    assert "renders for each record" in message
    assert "only data reaches the per-record render" in message


def test_a_per_record_prompt_cannot_include_a_template(tmp_path):
    (tmp_path / "templates" / "partials").mkdir(parents=True)
    (tmp_path / "templates" / "partials" / "kind.j2").write_text("{{ source.page_content }}")
    with pytest.raises(TemplateRenderingError, match="include"):
        _load(
            tmp_path,
            "actions:\n  - name: a\n    prompt: |\n"
            + _block("{% include 'partials/kind.j2' %} of {{ source.page_id }}"),
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
    prompt: "{% for item in source.entries %}{% set label = item.name %}- {{ label }}{% endfor %}"
{% endfor %}
""",
    )

    actions = _actions(data)
    assert actions["s2"]["intent"] == "Stage 2"
    assert actions["s2"]["prompt"] == (
        "{% for item in source.entries %}{% set label = item.name %}- {{ label }}{% endfor %}"
    )


# ── a name looked up at load that a record supplies fails the load ────────


@pytest.mark.parametrize(
    "workflow, name",
    [
        pytest.param(
            "actions:\n  - name: facts\n    kind: tool\n"
            '{% if facts is defined %}\n  - name: b\n    prompt: "x"\n{% endif %}\n',
            "facts",
            id="action-tested-around-actions",
        ),
        pytest.param(
            "{% macro note() %}{% if source is defined %}S{% endif %}{% endmacro %}\n"
            'actions:\n  - name: a\n    prompt: "{{ note() }}"\n',
            "source",
            id="source-tested-in-a-macro-a-prompt-calls",
        ),
    ],
)
def test_a_record_name_tested_at_load_fails_the_load(tmp_path, workflow, name):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(tmp_path, workflow)

    assert f"'{name}' is looked up while the workflow loads" in str(raised.value)


def test_a_version_variable_tested_outside_a_versioned_action_answers_no(tmp_path):
    data = _load(
        tmp_path,
        'actions:\n  - name: a\n    model_name: "{% if i is defined %}m{{ i }}{% else %}m{% endif %}"\n',
    )

    assert _actions(data)["a"]["model_name"] == "m"


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


# ── errors name the problem ────────────────────────────────────────────────


def test_a_yaml_typo_beside_a_per_record_prompt_names_the_kept_prompt_on_its_line(tmp_path):
    with pytest.raises(ConfigurationError) as raised:
        _load(
            tmp_path,
            "actions:\n  - name: a\n    prompt: |\n      Summarise\n      {{ source.text }}\n"
            "   intent: x\n",
        )

    assert "'source'" not in str(raised.value)
    lines = raised.value.context["rendered_content"].splitlines()
    assert lines[2] == "    prompt: <the value at line 3 of wf.yml, kept for each record>"
    assert lines[raised.value.context["line"] - 1] == "   intent: x"


def test_a_structural_condition_on_a_name_nothing_defines_names_only_it(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            'actions:\n  - name: write\n    prompt: "Summarise {{ source.text }}"\n'
            "{% if enable_validation %}\n  - name: v\n    prompt: y\n{% endif %}\n",
        )

    message = str(raised.value)
    assert "'enable_validation' is undefined" in message
    assert "'source'" not in message


def test_an_alias_of_a_per_record_prompt_gets_the_same_prompt(tmp_path):
    data = _load(
        tmp_path,
        'actions:\n  - name: a\n    prompt: &shared "Summarise {{ source.text }}"\n'
        "  - name: b\n    prompt: *shared\n",
    )

    assert _actions(data)["b"]["prompt"] == "Summarise {{ source.text }}"


# ── the per-record prompt is the YAML value the file wrote ────────────────


@pytest.mark.parametrize(
    "value, prompt",
    [
        pytest.param(
            '"Classify {{ source.text | default("none") }}"',
            'Classify {{ source.text | default("none") }}',
            id="double-quotes-inside-a-double-quoted-tag",
        ),
        pytest.param("'It''s {{ source.x }}'", "It's {{ source.x }}", id="single-quoted"),
        pytest.param("{{ source.x }} rest", "{{ source.x }} rest", id="plain-opening-on-a-tag"),
        pytest.param(
            ">\n      Hello {{ source.x }}\n      and more",
            "Hello {{ source.x }} and more\n",
            id="folded",
        ),
        pytest.param("|+\n      Hello {{ source.x }}\n", "Hello {{ source.x }}\n\n\n", id="kept"),
        pytest.param(
            "|\n      Hello {{ source.x }}\n{% if source.y %}\n      Y\n{% endif %}\n      Bye",
            "Hello {{ source.x }}\n{% if source.y %}\nY\n{% endif %}\nBye\n",
            id="tag-lines-left-of-the-block",
        ),
        pytest.param(
            ">\n      {% raw %}{{ keep }}\n      next{% endraw %} {{ source.x }}",
            "{% raw %}{{ keep }} next{% endraw %} {{ source.x }}\n",
            id="folded-raw-block",
        ),
        pytest.param(
            "|\n      {% raw %}\n      {{ keep }}\n        indented\n      {% endraw %}\n"
            "      {{ source.x }}",
            "{% raw %}\n{{ keep }}\n  indented\n{% endraw %}\n{{ source.x }}\n",
            id="literal-raw-block",
        ),
    ],
)
def test_a_per_record_prompt_is_the_value_yaml_reads(tmp_path, value, prompt):
    data = _load(tmp_path, f"actions:\n  - name: a\n    prompt: {value}\n\n    intent: x\n")

    assert _actions(data)["a"]["prompt"] == prompt


def test_load_time_data_reaches_the_record_unchanged(tmp_path):
    values = {
        "text": 'café 😀 "quoted" \\ {{ not a tag }} %} ${i}',
        "number": -1.5e-07,
        "flag": False,
        "nothing": None,
        "nested": {"a": [1, (2, 3)], "b": {"c": "x"}},
    }
    sets = "".join(f"{{% set {k} = {v!r} %}}" for k, v in values.items()).replace("None", "none")
    data = _load(
        tmp_path,
        sets + "\nactions:\n  - name: a\n    prompt: |\n"
        "      {% if source %}{{ [text, number, flag, nothing, nested] | tojson }}{% endif %}\n",
    )

    sent = PromptPreparationService._render_prompt_template(
        _actions(data)["a"]["prompt"], {"source": {"x": 1}}
    )
    assert json.loads(sent) == [
        values["text"],
        values["number"],
        False,
        None,
        {"a": [1, [2, 3]], "b": {"c": "x"}},
    ]


def test_a_prompt_reading_an_action_a_loop_names_renders_per_record(tmp_path):
    data = _load(
        tmp_path,
        """\
actions:
{% for n in [1, 2] %}
  - name: stage_{{ n }}
    prompt: "Stage {{ n }}: {{ source.text }}"
{% endfor %}
  - name: last
    dependencies: [stage_2]
    prompt: "After {{ stage_2.answer }}"
""",
    )

    assert _actions(data)["last"]["prompt"] == "After {{ stage_2.answer }}"


@pytest.mark.parametrize(
    "workflow, prompt",
    [
        pytest.param(
            "actions:\n  - name: a\n    prompt:\n      Summarise this page {{ source.page_id }}\n"
            "      in one line.\n",
            "Summarise this page {{ source.page_id }} in one line.",
            id="plain-value-on-the-lines-below-the-key",
        ),
        pytest.param(
            'actions:\n  - name: a\n    prompt:  # one line\n\n      "Summarise {{ source.page_id }}\n'
            '      in one line."\n',
            "Summarise {{ source.page_id }} in one line.",
            id="quoted-value-below-a-comment",
        ),
        pytest.param(
            "actions:\n  - name: a\n    prompt:\n      |\n      Summarise {{ source.page_id }}\n"
            "      {% if source.x %}X{% endif %}\n    intent: x\n",
            "Summarise {{ source.page_id }}\n{% if source.x %}X{% endif %}\n",
            id="block-header-below-the-key",
        ),
        pytest.param(
            'actions:\n  - {name: a, intent: x, prompt: "Summarize {{ source.text }}"}\n',
            "Summarize {{ source.text }}",
            id="flow-mapping",
        ),
        pytest.param(
            'actions:\n  - {name: a,  # the summary\n     prompt: "Summarize {{ source.text }}"}\n',
            "Summarize {{ source.text }}",
            id="flow-mapping-over-several-lines",
        ),
        pytest.param(
            'actions: [{name: a, prompt: "Summarize {{ source.text }}"}]\n',
            "Summarize {{ source.text }}",
            id="flow-sequence-of-actions",
        ),
        pytest.param(
            'actions: [{name: a,\nprompt: "Summarize {{ source.text }}"}]\n',
            "Summarize {{ source.text }}",
            id="flow-sequence-going-on-at-the-keys-column",
        ),
    ],
)
def test_a_per_record_prompt_written_in_any_yaml_form_is_kept_for_the_record(
    tmp_path, workflow, prompt
):
    """These forms were rendered at load, where the record's names fail it."""
    data = _load(tmp_path, workflow)

    assert _actions(data)["a"]["prompt"] == prompt


def test_a_version_value_on_the_line_below_its_key_renders_per_version(tmp_path):
    data = _load(
        tmp_path,
        "actions:\n  - name: m\n    versions: {range: [1, 2]}\n    intent:\n"
        '      "Version {{ i }}"\n    prompt: "x"\n'
        '  - {name: n, versions: {range: [1, 2]}, model_name: "m{{ i }}", prompt: "y {{ i }}"}\n',
    )

    actions = _actions(data)
    assert [actions[f"m_{i}"]["intent"] for i in (1, 2)] == ["Version 1", "Version 2"]
    assert [actions[f"n_{i}"]["model_name"] for i in (1, 2)] == ["m1", "m2"]
    assert actions["n_2"]["prompt"] == "y {{ i }}"


def test_a_mapping_below_a_key_is_not_read_as_its_value(tmp_path):
    data = _load(
        tmp_path,
        "defaults:\n  {{ '' }}\n  model_name: m\nactions:\n  - name: m\n"
        "    versions: {range: [1, 2]}\n    model_kwargs:\n      {{ '' }}\n"
        '      temperature: "0.{{ i }}"\n    prompt: "x"\n',
    )

    assert data["defaults"] == {"model_name": "m"}
    assert _actions(data)["m_2"]["model_kwargs"] == {"temperature": "0.2"}


@pytest.mark.parametrize(
    "upstream",
    [
        pytest.param(
            "{% macro tool(action_name) %}\n  - name: {{ action_name }}\n    kind: tool\n"
            "{% endmacro %}\n{{ tool('extract_facts') }}\n",
            id="named-by-a-macro-parameter",
        ),
        pytest.param(
            "{% for n in ['extract_facts'] %}\n  - name: {{ n }}\n    kind: tool\n{% endfor %}\n",
            id="named-by-a-loop-variable",
        ),
        pytest.param("  - {name: extract_facts, kind: tool}\n", id="named-in-a-flow-mapping"),
    ],
)
def test_a_prompt_reading_an_action_the_file_names_by_a_tag_renders_per_record(tmp_path, upstream):
    """The load knew only literal `name:` lines, so it rendered the prompt and failed."""
    data = _load(
        tmp_path,
        "actions:\n" + upstream + "  - name: validate\n    dependencies: [extract_facts]\n"
        '    prompt: "Validate these facts: {{ extract_facts.facts }}"\n',
    )

    assert _actions(data)["validate"]["prompt"] == "Validate these facts: {{ extract_facts.facts }}"


def test_a_prompt_reading_a_name_that_is_no_action_still_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            "actions:\n{% for n in ['facts'] %}\n  - name: {{ n }}\n{% endfor %}\n"
            '  - name: write\n    prompt: "Write about {{ topic }}."\n',
        )

    assert "'topic' is undefined" in str(raised.value)


def test_a_guarded_name_in_a_prompt_of_load_time_names_still_renders_at_load(tmp_path):
    data = _load(
        tmp_path,
        "{% set tone = 'plain' %}\nactions:\n"
        '  - name: a\n    prompt: "{% if debug is defined %}D{% endif %}Be {{ tone }}."\n',
    )

    assert _actions(data)["a"]["prompt"] == "Be plain."


def test_a_version_value_in_a_load_loop_reads_the_loop_as_it_was_there(tmp_path):
    """Rendered once the loop has moved on, it would read the last pass for every one."""
    data = _load(
        tmp_path,
        "{% set ns = namespace(n=0) %}\nactions:\n{% for s in ['a', 'b'] %}"
        "{% set ns.n = ns.n + 1 %}\n  - name: act_{{ s }}\n    versions: {range: [1, 2]}\n"
        '    intent: "{{ ns.n }}-{{ i }} of {{ loop.length }} idx {{ loop.index }}"\n'
        '    prompt: "x"\n{% endfor %}\n',
    )

    intents = {name: action["intent"] for name, action in _actions(data).items()}
    assert intents == {
        "act_a_1": "1-1 of 2 idx 1",
        "act_a_2": "1-2 of 2 idx 1",
        "act_b_1": "2-1 of 2 idx 2",
        "act_b_2": "2-2 of 2 idx 2",
    }


def test_a_prompt_reading_a_versioned_actions_output_is_decided_per_record(tmp_path):
    prompt = "{% if act_1 is defined %}After {{ act_1.x }}{% else %}alone{% endif %}"
    data = _load(
        tmp_path,
        'actions:\n  - name: act\n    versions: {range: [1, 2]}\n    prompt: "v {{ i }}"\n'
        f'  - name: after\n    dependencies: [act_1]\n    prompt: "{prompt}"\n',
    )

    assert _actions(data)["after"]["prompt"] == prompt


def test_a_per_record_value_a_templates_file_computes_at_its_top_level_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            "actions:\n{{ block }}\n",
            templates={
                "actions.j2": '{% set block %}\n  - name: a\n    prompt: "Hi {{ source.x }}"\n'
                "{% endset %}\n"
            },
        )

    message = str(raised.value)
    assert "at its top level as it loaded" in message
    assert "Write it in a macro that the workflow calls" in message


def test_a_per_record_value_inside_text_the_file_builds_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError, match="must stand alone as a value"):
        _load(
            tmp_path,
            '{% set p %}\nprompt: "Hi {{ source.x }}"\n{% endset %}\nactions:\n  - name: a\n'
            '    description: "{{ p | trim }} and more"\n    prompt: "x"\n',
        )


def test_a_load_time_tag_that_breaks_a_per_record_prompts_yaml_fails_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(
            tmp_path,
            '{% set intro = "Line one\\nLine two" %}\nactions:\n  - name: a\n    prompt: |\n'
            "      {{ intro }}\n      {{ source.x }}\n    intent: x\n",
        )

    message = str(raised.value)
    assert "reads 'source', so it renders for each record" in message
    assert "once its load-time tags render it is no longer valid YAML" in message


def test_a_load_rendered_again_for_an_action_named_by_a_tag_keeps_what_templates_left(tmp_path):
    """The templates/ folder loads once, before the workflow renders, however often it does."""
    with pytest.raises(TemplateRenderingError, match="at its top level as it loaded"):
        _load(
            tmp_path,
            "actions:\n{{ block }}\n{% for n in ['facts'] %}\n  - name: {{ n }}\n{% endfor %}\n"
            '  - name: b\n    dependencies: [facts]\n    prompt: "Use {{ facts.x }}"\n',
            templates={
                "actions.j2": '{% set block %}\n  - name: a\n    prompt: "Hi {{ source.x }}"\n'
                "{% endset %}\n"
            },
        )


# ── a loaded prompt of several lines goes in as written ──────────────────


def _two_line_store(tmp_path: Path) -> None:
    (tmp_path / "prompt_store").mkdir(exist_ok=True)
    (tmp_path / "prompt_store" / "lp.md").write_text(
        "{prompt Two}\nLine one: {{ source.a }}\n  Line two # not a comment\n{end_prompt}\n"
    )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        pytest.param(
            '>\n      {{ load_prompt("lp.Two") }}\n      then\n      {{ source.b }}',
            "Line one: {{ source.a }}\n  Line two # not a comment then {{ source.b }}\n",
            id="folded-reading-a-record",
        ),
        pytest.param(
            '>\n      {{ load_prompt("lp.Two") }}\n      then\n      more',
            "Line one: {{ source.a }}\n  Line two # not a comment then more\n",
            id="folded",
        ),
        pytest.param(
            '{{ load_prompt("lp.Two") }}',
            "Line one: {{ source.a }}\n  Line two # not a comment",
            id="plain",
        ),
        pytest.param(
            "'{{ load_prompt(\"lp.Two\") }} {{ source.b }}'",
            "Line one: {{ source.a }}\n  Line two # not a comment {{ source.b }}",
            id="single-quoted-reading-a-record",
        ),
        pytest.param(
            '|\n      {%- set p = load_prompt("lp.Two") %}\n      {{ p }}',
            "Line one: {{ source.a }}\n  Line two # not a comment\n",
            id="through-a-variable",
        ),
    ],
)
def test_an_inline_prompt_puts_a_loaded_prompt_of_several_lines_in_as_written(
    tmp_path, prompt, expected
):
    _two_line_store(tmp_path)

    data = _load(tmp_path, f"actions:\n  - name: a\n    prompt: {prompt}\n    intent: x\n")

    assert _actions(data)["a"]["prompt"] == expected


def test_a_loaded_prompt_in_a_flow_mapping_goes_in_as_written(tmp_path):
    _two_line_store(tmp_path)

    data = _load(
        tmp_path,
        "actions:\n"
        "  - {name: a, intent: x, prompt: \"{{ load_prompt('lp.Two') }} {{ source.b }}\"}\n"
        "  - {name: b, intent: x, prompt: \"{{ load_prompt('lp.Two') }}\"}\n",
    )

    loaded = "Line one: {{ source.a }}\n  Line two # not a comment"
    assert _actions(data)["a"]["prompt"] == loaded + " {{ source.b }}"
    assert _actions(data)["b"]["prompt"] == loaded


def test_a_loaded_prompt_indented_by_a_filter_is_pasted_as_before(tmp_path):
    """A workflow that indents the loaded text itself keeps the prompt it had."""
    _two_line_store(tmp_path)

    data = _load(
        tmp_path,
        "actions:\n  - name: a\n    prompt: |\n"
        '      {{ load_prompt("lp.Two") | indent(6) }}\n      {{ source.b }}\n    intent: x\n',
    )

    assert _actions(data)["a"]["prompt"] == (
        "Line one: {{ source.a }}\n  Line two # not a comment\n{{ source.b }}\n"
    )


def test_a_loaded_prompt_in_a_versioned_action_gets_its_version_values(tmp_path):
    (tmp_path / "prompt_store").mkdir()
    (tmp_path / "prompt_store" / "lp.md").write_text(
        "{prompt V}\nStrategy ${i}\nof {{ source.a }}\n{end_prompt}\n"
    )

    data = _load(
        tmp_path,
        "actions:\n  - name: a\n    versions: {range: [1, 2]}\n    prompt: |\n"
        '      {{ load_prompt("lp.V") }}\n      Go.\n    intent: x\n',
    )

    assert [action["prompt"] for action in data["actions"]] == [
        "Strategy 1\nof {{ source.a }}\nGo.\n",
        "Strategy 2\nof {{ source.a }}\nGo.\n",
    ]
