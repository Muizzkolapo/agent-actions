"""A prompt written in the workflow file sends each record what the same prompt sends
from the prompt store, or the load fails saying why it cannot.

Each case puts the prompt inline in one action and in the prompt store for another, loads
the workflow once, and renders both compiled prompts with the same record the way a run
does. None of these prompts may be decided once, at load, for every record.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService

URGENT = {"source": {"page_id": "p0", "page_content": "urgent", "note": "call back"}}
ROUTINE = {"source": {"page_id": "p1", "page_content": "routine"}}


def _block(prompt: str) -> str:
    return "".join(f"      {line}\n" for line in prompt.splitlines())


def _load(tmp_path: Path, actions: str, prompt: str, templates: dict | None = None) -> dict:
    """Each action's compiled prompt, with `prompt` also in the store as `twin.P`."""
    (tmp_path / "prompt_store").mkdir(exist_ok=True)
    (tmp_path / "prompt_store" / "twin.md").write_text(f"{{prompt P}}\n{prompt}\n{{end_prompt}}\n")
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    for name, text in (templates or {}).items():
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(actions)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return {a["name"]: a.get("prompt") for a in yaml.safe_load(rendered)["actions"]}


def _twins(tmp_path: Path, prompt: str, extra: str = "", templates: dict | None = None) -> dict:
    return _load(
        tmp_path,
        "actions:\n"
        f"  - name: inline\n{extra}    prompt: |\n{_block(prompt)}"
        f"  - name: store\n{extra}    prompt: $twin.P\n",
        prompt,
        templates,
    )


def _sent(prompt: str, record: dict) -> str:
    return PromptPreparationService._render_prompt_template(prompt, record).rstrip("\n")


CAPTURE = "{% set kind %}{{ source.page_content }}{% endset %}"


@pytest.mark.parametrize(
    "prompt, records",
    [
        pytest.param(
            "{% macro decide() %}{% if caller() == 'urgent' %}ESCALATE{% else %}normal{% endif %}"
            " len={{ caller() | length }}{% endmacro %}"
            "{% call decide() %}{{ source.page_content }}{% endcall %} id={{ source.page_id }}",
            [URGENT, ROUTINE],
            id="caller-tested-in-a-macro",
        ),
        pytest.param(
            "{% macro low() %}{{ caller() | lower }}{% endmacro %}"
            "{% call low() %}{{ source.page_content | upper }}{% endcall %}",
            [URGENT, ROUTINE],
            id="caller-filtered-in-a-macro",
        ),
        pytest.param(
            CAPTURE + "{% for n in [1, 2] if kind == 'urgent' %}E{{ n }}{% endfor %}.",
            [URGENT, ROUTINE],
            id="loop-filter-on-a-capture",
        ),
        pytest.param(
            CAPTURE + "{% macro m(v=kind) %}{% if v == 'urgent' %}ESC{% else %}norm{% endif %}"
            "{% endmacro %}{{ m() }}",
            [URGENT, ROUTINE],
            id="macro-default-reads-a-capture",
        ),
        pytest.param(
            "{% set note = source.note %}{% if note is defined %}Note: {{ note }}{% endif %}"
            "|{{ source.page_id }}",
            [URGENT, ROUTINE],
            id="defined-test-on-a-name-set-per-record",
        ),
        pytest.param(
            "{% for r in source.refs %}{% if r is defined %}[{{ r }}]{% endif %}{% endfor %}",
            [{"source": {"refs": ["a", "b"]}}, {"source": {"refs": []}}],
            id="defined-test-on-a-loop-variable",
        ),
        pytest.param(
            "{% if source is defined %}S={{ source.page_id }}{% else %}none{% endif %}",
            [URGENT, ROUTINE],
            id="defined-test-on-source",
        ),
        pytest.param(
            CAPTURE + "{{ kind ~ '/' ~ source.page_id }}",
            [URGENT, ROUTINE],
            id="capture-and-record-name-in-one-tag",
        ),
        pytest.param(
            "{% set target %}{{ source.kind }}{% endset %}"
            "{% for item in source.entries %}{% if item.cat == target %}{{ item.name }} "
            "{% endif %}{% endfor %}",
            [
                {"source": {"kind": "a", "entries": [{"cat": "a", "name": "x"}]}},
                {"source": {"kind": "b", "entries": [{"cat": "a", "name": "y"}]}},
            ],
            id="capture-compared-inside-a-record-loop",
        ),
        pytest.param(
            CAPTURE + "[{{ kind | trim }}]",
            [{"source": {"page_content": " urgent "}}],
            id="trim-of-a-capture",
        ),
        pytest.param(
            "{% if source.note is defined %}\n  Note: {{ source.note }}\n{% endif %}\n"
            "Summarize {{ source.page_content }}",
            [URGENT, ROUTINE],
            id="if-body-indented-deeper-than-its-tags",
        ),
        pytest.param(
            "{% for f in source.refs %}\n  - {{ f }}\n{% endfor %}\nEnd {{ source.page_id }}",
            [{"source": {"page_id": "p0", "refs": ["a", "b"]}}],
            id="for-body-indented-deeper-than-its-tags",
        ),
        pytest.param(
            "{%- if source.note is defined %}\n  Note: {{ source.note }}\n{% endif %}\nDone",
            [URGENT, ROUTINE],
            id="trimmed-leading-if-with-an-indented-body",
        ),
        pytest.param(
            "Reply in this format:\n{% raw %}\n{{ name }}: {{ value }}\n  {{ nested }}\n"
            "{% endraw %}\nText: {{ source.page_content }}",
            [URGENT],
            id="raw-block-of-several-lines",
        ),
    ],
)
def test_the_inline_prompt_sends_what_the_store_prompt_sends(tmp_path, prompt, records):
    prompts = _twins(tmp_path, prompt)

    for record in records:
        assert _sent(prompts["inline"], record) == _sent(prompts["store"], record)


def test_a_defined_test_on_an_upstream_action_is_decided_per_record(tmp_path):
    prompt = (
        "{% if facts is defined %}FACTS: {{ facts.facts }}{% else %}RAW: "
        "{{ source.page_content }}{% endif %}"
    )
    prompts = _load(
        tmp_path,
        "actions:\n  - name: facts\n    kind: tool\n    impl: facts_of\n"
        f"  - name: inline\n    dependencies: [facts]\n    prompt: |\n{_block(prompt)}"
        "  - name: store\n    dependencies: [facts]\n    prompt: $twin.P\n",
        prompt,
    )
    record = {**URGENT, "facts": {"facts": "facts of p0"}}

    assert _sent(prompts["inline"], record) == "FACTS: facts of p0"
    assert _sent(prompts["inline"], ROUTINE) == _sent(prompts["store"], ROUTINE)


def test_a_defined_test_on_the_version_is_decided_per_version(tmp_path):
    prompt = (
        "{% if version is defined %}Version {{ version.i }} of {{ version.length }}"
        "{% else %}single {{ source.page_id }}{% endif %}"
    )
    prompts = _twins(tmp_path, prompt, extra="    versions:\n      range: [1, 2]\n")

    for i in (1, 2):
        record = {**URGENT, "version": {"i": i, "length": 2}, "i": i}
        assert _sent(prompts[f"inline_{i}"], record) == f"Version {i} of 2"
        assert _sent(prompts[f"inline_{i}"], record) == _sent(prompts[f"store_{i}"], record)


def test_a_templates_macro_that_tests_its_caller_per_record_fails_the_load(tmp_path):
    """The store prompt cannot call it at all; inline, it must not decide at load."""
    with pytest.raises((ConfigurationError, TemplateRenderingError)) as raised:
        _twins(
            tmp_path,
            "{% call bullet() %}{{ source.note | default('') }}{% endcall %}END",
            templates={
                "list.j2": "{% macro bullet() %}{% if caller() | trim %}- {{ caller() }}"
                "{% endif %}{% endmacro %}"
            },
        )

    assert "'bullet'" in str(raised.value)
