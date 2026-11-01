"""A config edit keeps the answers an action already holds.

After an edit to an action's model, prompt, schema, guard, context scope or dependencies,
the answers stand, so a model swapped partway through a long run loses nothing: records
not yet answered are answered under the edit, a warning names what changed, each prompt
trace row records the config it was answered under, and ``--rerun <action>`` answers the
action and its readers again. `bystander` reads nothing the edits touch; each tool logs a
line per record to `calls.log`, so a test sees which actions ran.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
FAULT = "fault.json"
CALLS = "calls.log"
ITEMS = ["alpha", "beta", "gamma"]
TEXT = {"alpha": "first item", "beta": "second item", "gamma": "third item"}
SAW_THE_ID = [f"{item}:-" for item in ITEMS]
SAW_THE_TEXT = [f"{item}:{TEXT[item]}" for item in ITEMS]
SCOPE = "observe: [stage_items.item_id, merge_direct.decision]"
WIDER_SCOPE = "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]"

CONFIG = """name: map_reduce_fanin_check
description: "a config edit keeps the answers"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source:
    type: local
    folder: ./staging
    file_type: [json]

actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope:
      observe: [source.item_id, source.text]

  - name: vote_direct
    kind: tool
    impl: cast_vote_direct
    dependencies: [stage_items]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_item: string }
    context_scope:
      observe: [stage_items.*]

  - name: merge_direct
    kind: tool
    impl: merge_votes
    dependencies: [vote_direct]
    intent: "Merge"
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { decision: string, n_votes: integer }
    context_scope:
      observe: [vote_direct.*]

  - name: bystander
    kind: tool
    impl: logged_bystander
    dependencies: [stage_items]
    intent: "Reads nothing the edits touch"
    schema: { seen: string }
    context_scope:
      observe: [stage_items.item_id]

  - name: recap
    kind: tool
    impl: logged_recap
    dependencies: [merge_direct]
    intent: "Write what it saw"
    schema: { saw: string }
    context_scope:
      observe: [stage_items.item_id, merge_direct.decision]

  - name: after_recap
    kind: tool
    impl: logged_reader
    dependencies: [recap]
    intent: "Read the recap"
    schema: { echoed: string }
    context_scope:
      observe: [recap.*, stage_items.item_id]

  - name: summary
    dependencies: [stage_items]
    intent: "Say what the item is"
    prompt: "Say what you see of {{ stage_items.item_id }}."
    schema: { said: string }
    context_scope:
      observe: [stage_items.item_id]
"""

TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


def _log(action: str, item: str) -> None:
    with open({CALLS!r}, "a") as calls:
        calls.write(action + ":" + item + "\\n")


@udf_tool()
def logged_recap(data: dict[str, Any]) -> dict[str, Any]:
    staged = data.get("stage_items") or {{}}
    item = staged.get("item_id", "?")
    fault = Path({FAULT!r})
    if fault.exists() and json.loads(fault.read_text())["item"] == item:
        raise KeyboardInterrupt()
    _log("recap", item)
    return {{"saw": item + ":" + staged.get("text", "-")}}


@udf_tool()
def logged_reader(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("stage_items") or {{}}).get("item_id", "?")
    _log("after_recap", item)
    return {{"echoed": (data.get("recap") or {{}}).get("saw", "?")}}


@udf_tool()
def logged_bystander(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("stage_items") or {{}}).get("item_id", "?")
    _log("bystander", item)
    return {{"seen": item}}
"""


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _config(root):
    return _workflow(root) / "agent_config" / f"{WORKFLOW}.yml"


def _statuses(root):
    return json.loads((_workflow(root) / "agent_io" / ".agent_status.json").read_text())


def _edit(root, old, new):
    text = _config(root).read_text()
    assert text.count(old) == 1, f"the config no longer has exactly one {old!r}"
    _config(root).write_text(text.replace(old, new))


def _agac(root, *args):
    """Run the command; ``printed`` is its output with the console's line wrapping undone."""
    result = run_agac(root, *args, env={"OPENAI_API_KEY": "sk-not-used"})
    result.printed = " ".join((result.stdout + result.stderr).split())
    return result


def _ran(root):
    """Which actions ran a record since the last call, as {action: sorted items}."""
    path = root / CALLS
    if not path.exists():
        return {}
    ran: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        action, item = line.split(":", 1)
        ran.setdefault(action, []).append(item)
    path.unlink()
    return {action: sorted(items) for action, items in ran.items()}


def _backend(root):
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _rows(root, action):
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _recap_saw(root):
    return sorted(row["content"]["recap"]["saw"] for row in _rows(root, "recap"))


def _reader_echoed(root):
    return sorted(row["content"]["after_recap"]["echoed"] for row in _rows(root, "after_recap"))


def _traces(root, action):
    backend = _backend(root)
    try:
        return backend.get_prompt_traces(action)
    finally:
        backend.close()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "tools" / WORKFLOW / "logged.py").write_text(TOOLS)
    _config(root).write_text(CONFIG)
    return root


@pytest.fixture
def completed(project):
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, result.printed
    assert _recap_saw(project) == SAW_THE_ID
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS, "bystander": ITEMS}
    return project


EDITS = [
    pytest.param(SCOPE, WIDER_SCOPE, "context scope", id="context-scope"),
    pytest.param(
        "dependencies: [merge_direct]\n",
        "dependencies: [merge_direct, stage_items]\n",
        "dependencies",
        id="dependencies",
    ),
    pytest.param(
        "schema: { saw: string }",
        "schema: { saw: string, note: string }",
        "action config (prompt/schema/guard)",
        id="schema",
    ),
]


@pytest.mark.parametrize(("old", "new", "label"), EDITS)
def test_an_edit_to_a_completed_action_keeps_its_answers_and_its_readers(
    completed, old, new, label
):
    _edit(completed, old, new)

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert _recap_saw(completed) == SAW_THE_ID
    assert _reader_echoed(completed) == SAW_THE_ID
    assert {name: _statuses(completed)[name]["status"] for name in ("recap", "after_recap")} == {
        "recap": "completed",
        "after_recap": "completed",
    }
    assert f"recap was edited since it completed ({label})" in result.printed
    assert "--rerun recap" in result.printed
    assert "resetting to pending" not in result.printed


def test_an_edit_to_the_workflow_default_model_runs_nothing_again(completed):
    _edit(completed, "  model_name: gpt-4o-mini\n", "  model_name: gpt-4o\n")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert "summary was edited since it completed (model)" in result.printed
    assert "resetting to pending" not in result.printed


def test_an_action_stopped_partway_keeps_what_it_finished_and_answers_the_rest_under_the_edit(
    project,
):
    (project / FAULT).write_text(json.dumps({"item": "beta"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode != 0, result.printed
    assert _ran(project).get("recap") == ["alpha"]

    (project / FAULT).unlink()
    _edit(project, SCOPE, WIDER_SCOPE)
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(project) == {"recap": ["beta", "gamma"], "after_recap": ITEMS}
    assert _recap_saw(project) == ["alpha:-", "beta:second item", "gamma:third item"]
    assert "recap was edited since its last run started (context scope)" in result.printed


def test_rerun_answers_the_action_and_its_readers_again_under_the_edit(completed):
    _edit(completed, SCOPE, WIDER_SCOPE)

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(completed) == SAW_THE_TEXT
    assert _reader_echoed(completed) == SAW_THE_TEXT

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert "was edited since" not in result.printed


def test_rerun_of_an_unedited_action_answers_it_and_its_readers_again(completed):
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}


def test_rerun_names_an_action_the_workflow_does_not_have(completed):
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "no_such_action")

    assert result.returncode != 0
    assert f"--rerun: 'no_such_action' is not an action of {WORKFLOW}" in result.printed
    assert _ran(completed) == {}


def test_each_prompt_trace_row_records_the_config_it_was_answered_under(completed):
    before = _statuses(completed)["summary"]["answered_under"]
    traces = _traces(completed, "summary")
    assert len(traces) == len(ITEMS)
    assert [json.loads(row["answered_under"]) for row in traces] == [before] * len(ITEMS)

    _edit(
        completed,
        '    intent: "Say what the item is"\n',
        '    intent: "Say what the item is"\n    model_name: gpt-4o\n',
    )
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "summary")

    assert result.returncode == 0, result.printed
    after = _statuses(completed)["summary"]["answered_under"]
    assert after["model_name"] == "gpt-4o"
    assert before["model_name"] == "gpt-4o-mini"
    assert [json.loads(row["answered_under"]) for row in _traces(completed, "summary")] == [
        after
    ] * len(ITEMS)
