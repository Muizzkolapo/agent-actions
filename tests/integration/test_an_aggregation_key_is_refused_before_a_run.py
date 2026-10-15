"""A workflow asking to group its inputs by a field is refused, instead of running ungrouped.

`reduce_key` was documented as the aggregation pattern: an action with several
dependencies got their outputs "merged and grouped by key", and the groups decided how
many times it ran. It never did. Written on the action it did not reach the runtime
config at all, and delivered the one way that did reach the merge the lookup found
nothing on any stored record — so the action ran once per input record, and the run
reported success with output identical to the same workflow without the key.

Three rows, two of them sharing `parent_id: X`. Grouped, the joining action runs twice.
Both runs here go through the real CLI, loader and expander; the refusal has to land
before any record is processed, and has to name where grouping is still reachable.
"""

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "aggregate_probe"
JOINED = "joined"
REPLACEMENT = "granularity: File"

ROWS = [
    {"parent_id": "X", "text": "one"},
    {"parent_id": "X", "text": "two"},
    {"parent_id": "Y", "text": "three"},
]

TOOLS = '''"""Two branches over one row, and an action that joins them."""

from typing import Any

from agent_actions import udf_tool


@udf_tool()
def probe_left(data: dict[str, Any]) -> dict[str, Any]:
    source = data.get("source") or {}
    return {"parent_id": source.get("parent_id", ""), "left_note": f"L:{source.get('text', '')}"}


@udf_tool()
def probe_right(data: dict[str, Any]) -> dict[str, Any]:
    source = data.get("source") or {}
    return {"parent_id": source.get("parent_id", ""), "right_note": f"R:{source.get('text', '')}"}


@udf_tool()
def probe_join(data: dict[str, Any]) -> dict[str, Any]:
    left = data.get("left") or {}
    right = data.get("right") or {}
    return {
        "parent_id": left.get("parent_id", ""),
        "joined": f"{left.get('left_note', '')}|{right.get('right_note', '')}",
    }
'''

# Substituted with `replace`, not `format`: an inline `schema: { ... }` is full of
# braces that `format` reads as fields of its own.
MARKER = "#__REDUCE_KEY__\n"
DECLARED = "    reduce_key: parent_id\n"

WORKFLOW_YML = """\
name: aggregate_probe
description: "Two branches aggregated by a shared field"
version: "1.0.0"
defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  model_vendor: agac-provider
  model_name: agac-mock
  api_key: AGAC_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: left
    kind: tool
    impl: probe_left
    intent: "One branch"
    schema: { parent_id: string, left_note: string }
    context_scope: { observe: [source.parent_id, source.text] }

  - name: right
    kind: tool
    impl: probe_right
    intent: "The other branch"
    schema: { parent_id: string, right_note: string }
    context_scope: { observe: [source.parent_id, source.text] }

  - name: joined
    kind: tool
    impl: probe_join
    dependencies: [left, right]
#__REDUCE_KEY__
    intent: "Join both branches, one call per parent_id"
    schema: { parent_id: string, joined: string }
    context_scope: { observe: [left.parent_id, left.left_note, right.right_note] }
"""

PROJECT_YML = """\
default_agent_config:
  api_key: AGAC_API_KEY
  prompt_debug: False
#__REDUCE_KEY__
schema_path: schema
tool_path: ["tools"]
"""


def _project(tmp_path: Path, *, surface: str) -> Path:
    """The same workflow twice, with the key on the action or in the project defaults.

    Both are places a project can put it: the action is where the docs showed it, and
    `default_agent_config:` is the only route that ever reached the merge.
    """
    root = tmp_path / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema").mkdir()

    (root / "agent_actions.yml").write_text(
        PROJECT_YML.replace(MARKER, "  reduce_key: parent_id\n" if surface == "project" else "")
    )
    (root / ".env").write_text("AGAC_API_KEY=not-used\n")
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(
        WORKFLOW_YML.replace(MARKER, DECLARED if surface == "action" else "")
    )
    (workflow_dir / "agent_io" / "staging" / "rows.json").write_text(json.dumps(ROWS))
    (root / "tools" / WORKFLOW / "probe_tools.py").write_text(TOOLS)
    return root


def _run(project: Path):
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    return result.returncode, " ".join((result.stdout + result.stderr).split())


@pytest.mark.parametrize("surface", ["action", "project"])
def test_a_workflow_asking_to_group_by_a_key_is_refused(surface, tmp_path):
    code, output = _run(_project(tmp_path, surface=surface))

    assert code != 0, f"the run accepted a key that groups nothing: {output}"
    assert "reduce_key" in output, f"the refusal does not name the key: {output}"
    assert "is no longer read" in output, (
        f"the refusal reads as a misspelling rather than a retired key: {output}"
    )


@pytest.mark.parametrize("surface", ["action", "project"])
def test_the_refusal_names_where_grouping_is_still_reachable(surface, tmp_path):
    """A reader told only to delete the key loses the grouping they asked for."""
    _, output = _run(_project(tmp_path, surface=surface))

    assert REPLACEMENT in output, (
        f"the refusal does not name File granularity, so the author is left with no "
        f"route to the grouping the key asked for: {output}"
    )


@pytest.mark.parametrize("surface", ["action", "project"])
def test_nothing_is_processed_before_the_refusal(surface, tmp_path):
    """The bug was a run that reported success: three records through the joining
    action, one per input row, where grouping asks for two."""
    project = _project(tmp_path, surface=surface)

    _, output = _run(project)

    assert "completed" not in output, f"the run processed records it should refuse: {output}"
    assert not (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").exists(), (
        "the refusal landed after the store was written"
    )


def test_the_same_workflow_without_the_key_still_runs(tmp_path):
    """Guard on the guard: the refusals above also pass if this project never ran.

    Without the key the fan-in is the shape it always was — one call per input record,
    both branches in its context — and that is what the key failed to change.
    """
    code, output = _run(_project(tmp_path, surface="none"))

    assert code == 0, output
    assert f"✓ {JOINED}" in output, output
    # Named, not a bare "3 records": the branches report that too, so an unnamed count
    # passes while the joining action regressed to one execution — the bug's own shape.
    assert f"✓ {JOINED} 3 records" in output, (
        f"the fan-in no longer runs once per input row: {output}"
    )
