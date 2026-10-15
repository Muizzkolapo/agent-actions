"""The load-time render has the same dict-method-name shadowing bug as the per-record one (1370).

A workflow-level `{% set %}` name whose value is a dict with an `items` key must render
that key when read as `name.items`, not the `items` bound method -- `LoadRender`'s own
`jinja2.Environment` must use the same key-first `getattr` as the per-record renderer.
"""

from pathlib import Path

import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

PROMPT = '  - name: a\n    intent: "x"\n    prompt: "Summarise {{ source.text }}"\n'


def _load(tmp_path: Path, workflow: str) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def test_a_load_time_dict_with_an_items_key_reads_the_key_not_the_method(tmp_path):
    data = _load(
        tmp_path,
        "{% set rec = {'items': ['x', 'y']} %}\n"
        'defaults:\n  model_name: "{{ rec.items }}"\nactions:\n' + PROMPT,
    )

    assert data["defaults"]["model_name"] == "['x', 'y']"
    assert "built-in method" not in data["defaults"]["model_name"]
