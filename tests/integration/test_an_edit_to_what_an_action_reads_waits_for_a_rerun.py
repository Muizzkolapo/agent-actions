"""An edit to what an action reads is named, and waits for ``--rerun`` to run it again.

An edit to an action's `context_scope` or `dependencies` is recorded with its answers. A run
after one keeps those answers and those of its readers and warns which action was edited;
``--rerun <action>`` answers it and its readers again under the edit. This module pins what
counts as such an edit, a retry after one, a batch action under one, and an action stopped
partway then rerun; `test_a_config_edit_keeps_the_answers.py` pins the plain keep.
`bystander` reads nothing the edits touch; each tool logs a line per record to `calls.log`.
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

STAMP_KEYS = ("context_scope_hash", "dependencies_hash")


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

    The last run's result, with what every run printed and the console's wrapping undone.
    """
    env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}
    result = run_agac(root, *args, env=env)
    printed = result.stdout + result.stderr
    for _ in range(3):
        if "run again to continue" not in " ".join((result.stdout + result.stderr).split()):
            break
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
        printed += result.stdout + result.stderr
    result.printed = " ".join(printed.split())
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
    assert _recap_saw(project) == SAW_THE_ID
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS, "bystander": ITEMS}
    return project


def test_a_drop_or_a_passthrough_added_counts_as_an_edit_to_the_context_scope(completed):
    _edit(completed, SCOPE, SCOPE + "\n      passthrough: [merge_direct.n_votes]")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "recap was edited since it completed (context scope)" in _output(result)
    assert _ran(completed) == {}

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, _output(result)
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}

    _edit(
        completed, "      passthrough: [merge_direct.n_votes]", "      drop: [merge_direct.n_votes]"
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "recap was edited since it completed (context scope)" in _output(result)
    assert _ran(completed) == {}


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(None, id="nothing-edited"),
        pytest.param(
            (SCOPE, "observe: [merge_direct.decision, stage_items.item_id, merge_direct.decision]"),
            id="scope-reordered-and-repeated",
        ),
    ],
)
def test_a_run_that_changes_nothing_the_action_reads_names_no_edit_and_runs_nothing(
    completed, edit
):
    if edit is not None:
        _edit(completed, *edit)

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "was edited since" not in _output(result)
    assert "resetting to pending" not in _output(result)
    assert _ran(completed) == {}


def test_a_store_stamped_before_these_edits_were_recorded_names_no_edit(completed):
    """Stamps written before this release hold neither digest: reading their absence as an
    edit would warn of an edit at every completed action of every workflow after the upgrade."""
    statuses = json.loads(_status_file(completed).read_text())
    for details in statuses.values():
        for stamp in (details, details.get("answered_under") or {}):
            for key in STAMP_KEYS:
                stamp.pop(key, None)
    _status_file(completed).write_text(json.dumps(statuses))

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "was edited since" not in _output(result)
    assert "resetting to pending" not in _output(result)
    assert _ran(completed) == {}


def test_rerun_of_an_action_stopped_partway_after_a_scope_edit_answers_every_record(project):
    """Without --rerun the record finished before the stop keeps what the old scope gave it."""
    (project / FAULT).write_text(json.dumps({"item": "beta", "raise": "interrupt"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode != 0, _output(result)
    assert _ran(project).get("recap") == ["alpha"]

    (project / FAULT).unlink()
    _edit(project, SCOPE, WIDER_SCOPE)
    result = _agac(project, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, _output(result)
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(project) == SAW_THE_TEXT
    assert _reader_echoed(project) == SAW_THE_TEXT


def test_a_retry_after_a_scope_edit_answers_only_what_it_names_and_the_edit_waits_for_rerun(
    project,
):
    """A retry answers only the records it names, under the edit, and leaves the stamp as it
    was: the next run still names the edit, and --rerun answers every record under it."""
    (project / FAULT).write_text(json.dumps({"item": "beta", "raise": "error"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, _output(result)
    assert _status(project, "recap") == "completed_with_failures", _output(result)
    (project / FAULT).unlink()
    _ran(project)

    _edit(project, SCOPE, WIDER_SCOPE)
    result = _agac(project, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert (
        "recap was edited since it completed (context scope). A retry answers only the records "
        "it names" in _output(result)
    )
    assert _ran(project).get("recap") == ["beta"]
    assert _recap_saw(project) == ["alpha:-", "beta:second item", "gamma:-"]

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "recap was edited since it completed (context scope)" in _output(result)
    assert _ran(project) == {}
    assert _recap_saw(project) == ["alpha:-", "beta:second item", "gamma:-"]

    result = _agac(project, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, _output(result)
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(project) == SAW_THE_TEXT


def test_a_batch_action_keeps_its_answers_under_an_edited_scope_until_a_rerun(project):
    _config(project).write_text(CONFIG % {"recap": BATCH_RECAP})
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, _output(result)
    assert _status(project, "recap") == "completed", _output(result)
    assert "first item" not in _batch_prompts(project)
    _ran(project)

    _edit(project, SCOPE, WIDER_SCOPE)
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "recap was edited since it completed (context scope)" in _output(result)
    assert _status(project, "recap") == "completed", _output(result)
    assert "first item" not in _batch_prompts(project)
    assert _ran(project) == {}

    result = _agac(project, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, _output(result)
    assert _status(project, "recap") == "completed", _output(result)
    assert "first item" in _batch_prompts(project)
    assert _ran(project) == {"after_recap": ITEMS}

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert "was edited since" not in _output(result)
    assert _ran(project) == {}
