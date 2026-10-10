"""A version merge run again keeps what it answered, and holds nothing its input lost (1318).

Before a merge ran, its versions were merged per file and written to the merge's own
target, the slot its answers are stored in, and the merge then walked that slot as its
input. A record carried from a run before was read from the same slot, so it came back
as the merged input in place of its answer: after `agac retry` of another record, and on
a resume after the merge stopped in a later file. A file every version came to hold
empty was not written at all, so the merge walked its own answers for it from the run
before as input, and stored them again.

Every run is its own `agac` process. Only the fault is stood in for: raised by the
merge's tool online, and in batch an answer the provider gives that is not a JSON
object, put in the held batch before the run that collects it.
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
MERGE = "merge_direct"
READER = "recap"
FAULT = "fault.json"

CONFIG = """name: map_reduce_fanin_check
description: "a version merge run again"
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
%(merge)s
  - name: recap
    kind: tool
    impl: saw_the_merge
    dependencies: [merge_direct]
    intent: "Read the merge"
    schema: { decision_seen: boolean }
    context_scope:
      observe: [merge_direct.*]
"""

ONLINE_MERGE = """
  - name: merge_direct
    kind: tool
    impl: merge_votes_unless_told
    dependencies: [vote_direct]
    intent: "Merge"
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { decision: string, n_votes: integer }
    context_scope:
      observe: [vote_direct.*]
"""

BATCH_MERGE = """
  - name: merge_direct
    dependencies: [vote_direct]
    run_mode: batch
    intent: "Merge"
    version_consumption: { source: vote_direct, pattern: merge }
    prompt: "Merge the votes into one decision."
    schema: { decision: string, n_votes: integer }
    context_scope:
      observe: [vote_direct.*]
"""

# The fault file names one item and what the tool raises when asked about it.
TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def merge_votes_unless_told(data: dict[str, Any]) -> dict[str, Any]:
    votes = [v for k, v in data.items() if k.startswith("vote_") and isinstance(v, dict)]
    fault = Path({FAULT!r})
    if fault.exists():
        told = json.loads(fault.read_text())
        if any(v.get("voted_item") == told["item"] for v in votes):
            if told["raise"] == "interrupt":
                raise KeyboardInterrupt()
            raise ValueError("no merge for " + told["item"])
    return {{"decision": "keep", "n_votes": len(votes)}}


@udf_tool()
def saw_the_merge(data: dict[str, Any]) -> dict[str, Any]:
    merged = data.get("merge_direct")
    return {{"decision_seen": isinstance(merged, dict) and "decision" in merged}}
"""

MODES = pytest.mark.parametrize("mode", ["online", "batch"])


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _staging(root):
    return _workflow(root) / "agent_io" / "staging"


def _config(root):
    return _workflow(root) / "agent_config" / f"{WORKFLOW}.yml"


def _status(root, action):
    path = _workflow(root) / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())[action]["status"]


def _stage(root, **files):
    shutil.rmtree(_staging(root))
    _staging(root).mkdir()
    for name, items in files.items():
        rows = [{"item_id": item, "text": f"{item} item"} for item in items]
        (_staging(root) / f"{name}.json").write_text(json.dumps(rows))


def _fail(root, item, raising="error"):
    (root / FAULT).write_text(json.dumps({"item": item, "raise": raising}))


def _stop_failing(root):
    (root / FAULT).unlink()


def _agac(root, *args, before_collect=None):
    """Run the command, then run again for each batch it leaves out, as a user does.

    *before_collect* is called on the project before each run that collects.
    """
    env = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}
    result = run_agac(root, *args, env=env)
    for _ in range(3):
        if "run again" not in result.stdout + result.stderr:
            break
        if before_collect is not None:
            before_collect(root)
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _output(result):
    return result.stdout + result.stderr


def _provider_fails(item):
    """The provider answers *item* with text, not the JSON object asked for."""

    def answer_badly(root):
        for held in (root / ".agac" / "batch_state").glob("*.json"):
            batch = json.loads(held.read_text())
            for task in batch["tasks"]:
                if item in json.dumps(task):
                    task["schema"] = {"type": "string"}
            held.write_text(json.dumps(batch))

    return answer_badly


def _rows(root, action):
    """What *action* stores, per file."""
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return {
            path: backend.read_target(action, path) for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def _item(row):
    return row["content"]["stage_items"]["item_id"]


def _answered_by_the_merge(rows):
    """The items whose row holds the merge's answer and whose lineage ends at the merge.

    A failed record's row holds no answer.
    """
    return sorted(
        _item(row)
        for row in rows
        if "decision" in (row.get("content", {}).get(MERGE) or {})
        and row["node_id"].startswith(f"{MERGE}_")
        and row["lineage"][-1] == row["node_id"]
    )


def _seen_by_the_reader(rows):
    """The items the reader found a decision for, and whose row still carries it."""
    return sorted(
        _item(row)
        for row in rows
        if row["content"][READER]["decision_seen"]
        and "decision" in (row["content"].get(MERGE) or {})
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "tools" / WORKFLOW / "merge_unless_told.py").write_text(TOOLS)
    return root


def _configure(root, mode):
    merge = ONLINE_MERGE if mode == "online" else BATCH_MERGE
    _config(root).write_text(CONFIG % {"merge": merge})


def _empty_and_run_from_the_first_stage(root, name):
    """Empty a staged file, and edit the first stage so it and everything below run again."""
    (_staging(root) / f"{name}.json").write_text("[]")
    _config(root).write_text(
        _config(root)
        .read_text()
        .replace(
            "    impl: stage_items\n",
            "    impl: stage_items\n    guard: { condition: 'true', on_false: \"skip\" }\n",
        )
    )


@MODES
def test_a_retry_of_one_merge_record_leaves_the_others_answers_as_they_were(project, mode):
    """The retry carried alpha and beta, and every record of the file with no failure,
    from the merge's own slot, which then held the merged input: their rows lost the
    merge's answer and ended at a version."""
    _configure(project, mode)
    _stage(project, items=["alpha", "beta", "gamma"], items2=["delta", "epsilon"])
    if mode == "online":
        _fail(project, "gamma")
        result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
        _stop_failing(project)
    else:
        result = _agac(
            project, "run", "-a", WORKFLOW, "--fresh", before_collect=_provider_fails("gamma")
        )

    assert result.returncode == 0, _output(result)
    assert _status(project, MERGE) == "completed_with_failures", _output(result)
    assert _answered_by_the_merge(_rows(project, MERGE)["items.json"]) == ["alpha", "beta"]

    result = _agac(project, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    merged = _rows(project, MERGE)
    assert _answered_by_the_merge(merged["items.json"]) == ["alpha", "beta", "gamma"], merged
    assert _answered_by_the_merge(merged["items2.json"]) == ["delta", "epsilon"], merged
    read = _rows(project, READER)
    assert _seen_by_the_reader(read["items.json"]) == ["alpha", "beta", "gamma"], read
    assert _seen_by_the_reader(read["items2.json"]) == ["delta", "epsilon"], read


def test_a_merge_stopped_in_a_later_file_keeps_the_answers_of_the_files_before(project):
    """The resume carried the first file's records from the merge's own slot, which
    then held the merged input, so the reader found no decision for any of them.

    Online only: a batch merge collects every file of its batches in one pass, and a
    pass that stops is collected again rather than run again.
    """
    _configure(project, "online")
    _stage(project, items=["alpha", "beta", "gamma"], items2=["delta", "epsilon"])
    _fail(project, "delta", raising="interrupt")

    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode != 0, _output(result)
    assert _answered_by_the_merge(_rows(project, MERGE)["items.json"]) == [
        "alpha",
        "beta",
        "gamma",
    ]

    _stop_failing(project)
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    merged = _rows(project, MERGE)
    assert _answered_by_the_merge(merged["items.json"]) == ["alpha", "beta", "gamma"], merged
    assert _answered_by_the_merge(merged["items2.json"]) == ["delta", "epsilon"], merged
    read = _rows(project, READER)
    assert _seen_by_the_reader(read["items.json"]) == ["alpha", "beta", "gamma"], read
    assert _seen_by_the_reader(read["items2.json"]) == ["delta", "epsilon"], read


@MODES
def test_a_file_every_version_holds_empty_leaves_the_merge_and_its_reader_holding_nothing(
    project, mode
):
    """Nothing was merged for the file, so the merge walked its own answers for it
    from the run before as input, and its reader read them again."""
    _configure(project, mode)
    _stage(project, kept=["alpha"], filtered=["beta", "gamma"])

    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, _output(result)
    assert _answered_by_the_merge(_rows(project, MERGE)["filtered.json"]) == ["beta", "gamma"]

    _empty_and_run_from_the_first_stage(project, "filtered")
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    assert _rows(project, "vote_direct_1").get("filtered.json", []) == []
    assert _rows(project, "vote_direct_2").get("filtered.json", []) == []
    merged = _rows(project, MERGE)
    assert merged.get("filtered.json", []) == [], merged
    assert _answered_by_the_merge(merged["kept.json"]) == ["alpha"], merged
    read = _rows(project, READER)
    assert read.get("filtered.json", []) == [], read
    assert _seen_by_the_reader(read["kept.json"]) == ["alpha"], read


@MODES
def test_a_retry_after_a_file_every_version_holds_empty_brings_none_of_it_back(project, mode):
    """The run that emptied the file walked the merge's answers for it as input, and so
    did the retry of a record of another file."""
    _configure(project, mode)
    _stage(project, kept=["alpha", "delta"], filtered=["beta", "gamma"])

    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")

    assert result.returncode == 0, _output(result)

    _empty_and_run_from_the_first_stage(project, "filtered")
    if mode == "online":
        _fail(project, "alpha")
        result = _agac(project, "run", "-a", WORKFLOW)
        _stop_failing(project)
    else:
        result = _agac(project, "run", "-a", WORKFLOW, before_collect=_provider_fails("alpha"))

    assert result.returncode == 0, _output(result)
    assert _status(project, MERGE) == "completed_with_failures", _output(result)

    result = _agac(project, "retry", "-a", WORKFLOW)

    assert result.returncode == 0, _output(result)
    merged = _rows(project, MERGE)
    assert merged.get("filtered.json", []) == [], merged
    assert _answered_by_the_merge(merged["kept.json"]) == ["alpha", "delta"], merged
    read = _rows(project, READER)
    assert read.get("filtered.json", []) == [], read
    assert _seen_by_the_reader(read["kept.json"]) == ["alpha", "delta"], read
