"""`env(name, default)` reads the process environment while the workflow file loads."""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates

VARIABLE = "AGAC_TEST_WORKFLOW_ENV"


@pytest.fixture(autouse=True)
def _unset(monkeypatch):
    monkeypatch.delenv(VARIABLE, raising=False)


def _load(tmp_path: Path, workflow: str, templates: dict[str, str] | None = None) -> dict:
    config = tmp_path / "wf.yml"
    config.write_text(workflow)
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    for name, text in (templates or {}).items():
        (folder / name).write_text(text)
    rendered = render_pipeline_with_templates(
        config, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def _defaults(value: str) -> str:
    return f"""\
name: wf
defaults:
  run_mode: {value}
actions:
  - name: act
    intent: "do a thing"
"""


def test_a_set_variable_is_its_value(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "batch")

    data = _load(tmp_path, _defaults(f"{{{{ env('{VARIABLE}', 'online') }}}}"))

    assert data["defaults"]["run_mode"] == "batch"


@pytest.mark.parametrize(
    "call", [f"env('{VARIABLE}', 'online')", f"env('{VARIABLE}', default='online')"]
)
def test_an_unset_variable_is_its_default(tmp_path, call):
    data = _load(tmp_path, _defaults(f"{{{{ {call} }}}}"))

    assert data["defaults"]["run_mode"] == "online"


def test_an_empty_variable_counts_as_set(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "")

    data = _load(tmp_path, _defaults(f"\"[{{{{ env('{VARIABLE}', 'online') }}}}]\""))

    assert data["defaults"]["run_mode"] == "[]"


def test_an_unset_variable_without_a_default_refuses_the_load(tmp_path):
    with pytest.raises(TemplateRenderingError) as raised:
        _load(tmp_path, _defaults(f"{{{{ env('{VARIABLE}') }}}}"))

    assert str(raised.value) == (
        f"Error rendering YAML template from '{tmp_path / 'wf.yml'}': env('{VARIABLE}') reads "
        f"'{VARIABLE}', which the environment does not hold, and gives no default. Set "
        f"{VARIABLE} in the environment or in the project's .env, or give a default: "
        f"env('{VARIABLE}', '...')"
    )


def test_a_versioned_value_reads_it(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "m")
    workflow = f"""\
name: wf
actions:
  - name: vote
    intent: "vote"
    versions:
      param: n
      range: [1, 2]
    model_name: "{{{{ env('{VARIABLE}') }}}}-{{{{ n }}}}"
"""

    data = _load(tmp_path, workflow)

    assert [a["model_name"] for a in data["actions"]] == ["m-1", "m-2"]


def test_a_templates_macro_reads_it(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "batch")
    macro = f"{{% macro mode() %}}{{{{ env('{VARIABLE}') }}}}{{% endmacro %}}\n"

    data = _load(tmp_path, _defaults("{{ mode() }}"), {"modes.j2": macro})

    assert data["defaults"]["run_mode"] == "batch"


def test_a_per_record_prompt_gets_its_value_at_load(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "warm")
    workflow = f"""\
name: wf
actions:
  - name: act
    intent: "do a thing"
    prompt: "Tone {{{{ env('{VARIABLE}') }}}} for {{{{ source.text }}}}"
"""

    data = _load(tmp_path, workflow)

    assert data["actions"][0]["prompt"] == "Tone warm for {{ source.text }}"


def test_a_per_record_prompt_cannot_call_it_inside_a_block(tmp_path, monkeypatch):
    monkeypatch.setenv(VARIABLE, "warm")
    workflow = f"""\
name: wf
actions:
  - name: act
    intent: "do a thing"
    prompt: "{{% if source.text %}}{{{{ env('{VARIABLE}') }}}}{{% endif %}}"
"""

    with pytest.raises(TemplateRenderingError, match="uses 'env', a function of the load"):
        _load(tmp_path, workflow)
