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
