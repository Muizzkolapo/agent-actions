"""An edit to what an action reads runs it again, with what reads it (1332).

A completed action was run again after an edit only when its prompt, schema, guard or
model changed. An edit to its `context_scope` or its `dependencies` left it `already
complete`, holding answers produced under what it read before, and so did what reads it.
An action stopped partway kept the records it had finished under the old scope.

`recap` reads one field of `stage_items` and writes what it saw; `after_recap` reads
`recap`; `bystander` reads `stage_items` and nothing the edits touch. Each tool writes a
line to `calls.log` per record, so a test sees which actions ran. Every run is its own
`agac` process. Only the fault is stood in for: a tool raising for a named item.
"""

import json
import os
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
SAW_THE_TEXT = [f"{item}:{TEXT[item]}" for item in ITEMS]

CONFIG = """name: map_reduce_fanin_check
description: "an edit to what an action reads"
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
%(recap)s
  - name: after_recap
    kind: tool
    impl: logged_reader
    dependencies: [recap]
    intent: "Read the recap"
    schema: { echoed: string }
    context_scope:
      observe: [recap.*, stage_items.item_id]
"""

ONLINE_RECAP = """
  - name: recap
    kind: tool
    impl: logged_recap
    dependencies: [merge_direct]
    intent: "Write what it saw"
    schema: { saw: string }
    context_scope:
      observe: [stage_items.item_id, merge_direct.decision]
"""

BATCH_RECAP = """
  - name: recap
    run_mode: batch
    dependencies: [merge_direct]
    intent: "Write what it saw"
    prompt: "Say what you see of {{ stage_items.item_id }}."
    schema: { saw: string }
    context_scope:
      observe: [stage_items.item_id, merge_direct.decision]
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
    if fault.exists():
        told = json.loads(fault.read_text())
        if told["item"] == item:
            if told["raise"] == "interrupt":
                raise KeyboardInterrupt()
            raise ValueError("no recap for " + item)
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

STAMP_KEYS = ("context_scope_hash", "dependencies_hash", "udf_source_hash")


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _config(root):
    return _workflow(root) / "agent_config" / f"{WORKFLOW}.yml"


def _status_file(root):
    return _workflow(root) / "agent_io" / ".agent_status.json"


def _status(root, action):
    return json.loads(_status_file(root).read_text())[action]["status"]


def _edit(root, old, new):
    text = _config(root).read_text()
    assert text.count(old) == 1, f"the config no longer has exactly one {old!r}"
    _config(root).write_text(text.replace(old, new))


def _agac(root, *args):
    """Run the command, then run again for each batch it leaves out, as a user does.

    The last run's result, with what every run printed.
    """
    env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}
    result = run_agac(root, *args, env=env)
    printed = result.stdout + result.stderr
    for _ in range(3):
        if "run again" not in result.stdout + result.stderr:
            break
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
        printed += result.stdout + result.stderr
    result.printed = printed
    return result


def _output(result):
    return result.printed


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


def _rows(root, action):
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
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


def _batch_prompts(root):
    """Every prompt the mock provider was sent in a batch, as one string."""
    return "\n".join(held.read_text() for held in (root / ".agac" / "batch_state").glob("*.json"))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "tools" / WORKFLOW / "logged.py").write_text(TOOLS)
    _config(root).write_text(CONFIG % {"recap": ONLINE_RECAP})
    return root


@pytest.fixture
def completed(project):
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, _output(result)
    assert _recap_saw(project) == [f"{item}:-" for item in ITEMS]
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS, "bystander": ITEMS}
    return project


def test_an_edit_to_the_context_scope_runs_the_action_and_its_readers_under_it(completed):
    _edit(
        completed,
        "observe: [stage_items.item_id, merge_direct.decision]",
        "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]",
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "context scope changed for recap, resetting to pending" in _output(result)
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(completed) == SAW_THE_TEXT
    assert _reader_echoed(completed) == SAW_THE_TEXT

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {}


def test_an_edit_to_tool_source_runs_it_and_its_readers_again(completed):
    tool = completed / "tools" / WORKFLOW / "logged.py"
    source = tool.read_text()
    old = 'return {"saw": item + ":" + staged.get("text", "-")}'
    assert source.count(old) == 1
    tool.write_text(source.replace(old, 'return {"saw": item + ":changed"}'))

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    ran = _ran(completed)
    assert ran["recap"] == ITEMS
    assert ran["after_recap"] == ITEMS
    assert _recap_saw(completed) == [f"{item}:changed" for item in ITEMS]
    assert _reader_echoed(completed) == [f"{item}:changed" for item in ITEMS]

    result = _agac(completed, "run", "-a", WORKFLOW)
    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {}


def test_an_interrupted_tool_with_edited_source_restarts_its_work(project):
    (project / FAULT).write_text(json.dumps({"item": "beta", "raise": "interrupt"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode != 0, _output(result)
    assert _ran(project).get("recap") == ["alpha"]

    (project / FAULT).unlink()
    tool = project / "tools" / WORKFLOW / "logged.py"
    source = tool.read_text()
    old = 'return {"saw": item + ":" + staged.get("text", "-")}'
    assert source.count(old) == 1
    tool.write_text(source.replace(old, 'return {"saw": item + ":changed"}'))
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _recap_saw(project) == [f"{item}:changed" for item in ITEMS]
    assert _reader_echoed(project) == [f"{item}:changed" for item in ITEMS]


def test_same_size_edit_with_unchanged_timestamp_executes_new_source(completed):
    tool = completed / "tools" / WORKFLOW / "logged.py"
    original = tool.read_text()
    timestamp = tool.stat()
    old = 'item + ":" + staged.get("text", "-")'
    assert original.count(old) == 1
    tool.write_text(original.replace(old, 'item + "!" + staged.get("text", "-")'))
    os.utime(tool, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))

    result = _agac(completed, "run", "-a", WORKFLOW)
    assert result.returncode == 0, _output(result)
    assert _recap_saw(completed) == [f"{item}!-" for item in ITEMS]


def test_a_drop_or_a_passthrough_added_counts_as_an_edit(completed):
    _edit(
        completed,
        "observe: [stage_items.item_id, merge_direct.decision]",
        "observe: [stage_items.item_id, merge_direct.decision]\n"
        "      passthrough: [merge_direct.n_votes]",
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}

    _edit(
        completed, "      passthrough: [merge_direct.n_votes]", "      drop: [merge_direct.n_votes]"
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}


def test_an_edit_to_the_dependencies_runs_the_action_and_its_readers_again(completed):
    _edit(
        completed, "dependencies: [merge_direct]\n", "dependencies: [merge_direct, stage_items]\n"
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "dependencies changed for recap, resetting to pending" in _output(result)
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {}


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(None, id="nothing-edited"),
        pytest.param(
            (
                "observe: [stage_items.item_id, merge_direct.decision]",
                "observe: [merge_direct.decision, stage_items.item_id, merge_direct.decision]",
            ),
            id="scope-reordered-and-repeated",
        ),
    ],
)
def test_a_run_that_changes_nothing_the_action_reads_runs_nothing(completed, edit):
    if edit is not None:
        _edit(completed, *edit)

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "resetting to pending" not in _output(result)
    assert _ran(completed) == {}


def test_a_store_stamped_before_these_edits_were_recorded_does_not_run_again(completed):
    """Stamps written before this release hold neither digest: reading their absence as an
    edit would run every completed action of every workflow once after the upgrade."""
    statuses = json.loads(_status_file(completed).read_text())
    for details in statuses.values():
        for stamp in (details, details.get("answered_under") or {}):
            for key in ("context_scope_hash", "dependencies_hash"):
                stamp.pop(key, None)
    _status_file(completed).write_text(json.dumps(statuses))

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "resetting to pending" not in _output(result)
    assert _ran(completed) == {}


def test_a_store_without_source_stamps_refreshes_udf_actions(completed):
    statuses = json.loads(_status_file(completed).read_text())
    for details in statuses.values():
        for stamp in (details, details.get("answered_under") or {}):
            stamp.pop("udf_source_hash", None)
    _status_file(completed).write_text(json.dumps(statuses))
    tool = completed / "tools" / WORKFLOW / "logged.py"
    source = tool.read_text()
    old = 'return {"saw": item + ":" + staged.get("text", "-")}'
    assert source.count(old) == 1
    tool.write_text(source.replace(old, 'return {"saw": item + ":changed"}'))

    result = _agac(completed, "run", "-a", WORKFLOW)
    assert result.returncode == 0, _output(result)
    assert _recap_saw(completed) == [f"{item}:changed" for item in ITEMS]
    assert _reader_echoed(completed) == [f"{item}:changed" for item in ITEMS]


def test_an_action_stopped_partway_answers_everything_again_after_a_scope_edit(project):
    """The resume kept the record finished before the stop, answered under the old scope."""
    (project / FAULT).write_text(json.dumps({"item": "beta", "raise": "interrupt"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode != 0, _output(result)
    assert _ran(project).get("recap") == ["alpha"]

    (project / FAULT).unlink()
    _edit(
        project,
        "observe: [stage_items.item_id, merge_direct.decision]",
        "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]",
    )
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _recap_saw(project) == SAW_THE_TEXT
    assert _reader_echoed(project) == SAW_THE_TEXT
    assert "recap was edited since its last run started" in _output(result)


def test_a_retry_after_a_scope_edit_leaves_the_edit_to_the_next_run(project):
    """A retry answers only the records it names. Stamped with the edited scope, the next
    run read nothing to apply and the other records kept what the old scope gave them."""
    (project / FAULT).write_text(json.dumps({"item": "beta", "raise": "error"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, _output(result)
    assert _status(project, "recap") == "completed_with_failures", _output(result)
    (project / FAULT).unlink()
    _ran(project)

    _edit(
        project,
        "observe: [stage_items.item_id, merge_direct.decision]",
        "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]",
    )
    result = _agac(project, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "recap was edited since it completed" in _output(result)
    assert _ran(project).get("recap") == ["beta"]

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(project) == SAW_THE_TEXT


def test_a_batch_action_runs_again_under_an_edited_scope(project):
    _config(project).write_text(CONFIG % {"recap": BATCH_RECAP})
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, _output(result)
    assert _status(project, "recap") == "completed", _output(result)
    assert "first item" not in _batch_prompts(project)
    _ran(project)

    _edit(
        project,
        "observe: [stage_items.item_id, merge_direct.decision]",
        "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]",
    )
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "context scope changed for recap, resetting to pending" in _output(result)
    assert _status(project, "recap") == "completed", _output(result)
    assert "first item" in _batch_prompts(project)
    assert _ran(project) == {"after_recap": ITEMS}

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "resetting to pending" not in _output(result)
    assert _ran(project) == {}
