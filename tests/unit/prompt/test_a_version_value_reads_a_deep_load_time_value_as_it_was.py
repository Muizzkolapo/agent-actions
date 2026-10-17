"""A value left for its version reads a load-time name as the load had it there (1467).

The snapshot was a `copy.deepcopy`, which fails on a value nested about 500 levels deep;
the failure was caught and the live object read instead, so a change the file made to it
further down reached the version's render.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.deferred_values import _frozen
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _load(tmp_path: Path, workflow: str) -> dict:
    folder = tmp_path / "templates"
    folder.mkdir(exist_ok=True)
    path = tmp_path / "wf.yml"
    path.write_text(workflow)
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)


def _workflow(depth: int) -> str:
    return (
        "{% set deep = [] %}{% set ns = namespace(cur=deep) %}"
        f"{{% for _ in range({depth}) %}}{{% set nxt = [] %}}"
        "{% set _ = ns.cur.append(nxt) %}{% set ns.cur = nxt %}{% endfor %}\n"
        "actions:\n"
        "  - name: a\n"
        "    versions: {range: [1, 2]}\n"
        '    intent: "{{ i }} of {{ deep | length }}"\n'
        '    prompt: "x {{ i }}"\n'
        "{% set _ = deep.append('added later') %}{% set _ = ns.cur.append('deepest') %}\n"
    )


@pytest.mark.parametrize("depth", [3, 800])
def test_a_later_change_to_a_load_time_value_does_not_reach_a_version_value(tmp_path, depth):
    data = _load(tmp_path, _workflow(depth))

    assert [action["intent"] for action in data["actions"]] == ["1 of 1", "2 of 1"]


def test_the_snapshot_of_a_value_800_levels_deep_is_a_copy_at_every_level():
    live: list = []
    cur = live
    for _ in range(800):
        nxt: list = []
        cur.append(nxt)
        cur = nxt

    frozen = _frozen(live)
    cur.append("changed after the snapshot")
    live.append("and at the top")

    assert len(frozen) == 1
    level = frozen
    for _ in range(800):
        level = level[0]
    assert level == []
