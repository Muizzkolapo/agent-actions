"""A drop on a version merge keeps what it drops away from the merge (1293).

The load-time pruning of drops on namespaces outside an action's ancestors walked
``dependencies`` without expanding a version base, so a merge depending on ``vote``
had no ancestors but the name ``vote`` itself. Every drop it carried, naming a version
branch or an action above the branches, was removed, and the dropped fields reached
the merge's tool and its prompt.

Every run is its own ``agac`` process. Only the fault ``agac retry`` recovers from is
stood in for, raised by the merge's tool.
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

CONFIG = """name: map_reduce_fanin_check
description: "a drop on a version merge"
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

  - name: split_words
    kind: tool
    impl: split_words
    dependencies: [stage_items]
    intent: "Map"
    schema: { item_id: string, word: string, word_index: integer }
    context_scope:
      observe: [stage_items.*]

  - name: vote
    kind: tool
    impl: cast_vote
    dependencies: [split_words]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_word: string }
    context_scope:
      observe: [split_words.*]
%(merge)s"""

ONLINE_MERGE = """
  - name: merge_votes
    kind: tool
    impl: merge_and_tell
    dependencies: [vote]
    intent: "Merge"
    version_consumption: { source: vote, pattern: merge }
    schema: { seen: string }
    context_scope:
      observe: [vote.*, split_words.*]
      drop: [vote.voted_word, split_words.word]
"""

BATCH_MERGE = """
  - name: merge_votes
    dependencies: [vote]
    run_mode: batch
    intent: "Merge"
    version_consumption: { source: vote, pattern: merge }
    prompt: "Merge the votes into one decision."
    schema: { decision: string, n_votes: integer }
    context_scope:
      observe: [vote.*, split_words.*]
      drop: [vote.voted_word, split_words.word]
"""

TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def merge_and_tell(data: dict[str, Any]) -> dict[str, Any]:
    fault = Path({FAULT!r})
    item = (data.get("split_words") or {{}}).get("item_id")
    if fault.exists() and json.loads(fault.read_text())["item"] == item:
        raise ValueError("no merge for " + item)
    return {{"seen": json.dumps(data, sort_keys=True)}}
"""

# What the merge is given once the drops apply: each branch's vote, and the word's
# place but not the word.
KEPT = {
    "split_words": {"item_id", "word_index"},
    "vote_1": {"vote"},
    "vote_2": {"vote"},
}


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _env():
    return {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "sk-not-used"}


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


def _shape(given):
    return {namespace: set(fields) for namespace, fields in given.items()}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "tools" / WORKFLOW / "merge_and_tell.py").write_text(TOOLS)
    return root


def _configure(root, merge):
    config = _workflow(root) / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(CONFIG % {"merge": merge})


def _seen_by_the_merge(root):
    return {
        row["content"]["split_words"]["item_id"]
        + "/"
        + str(row["content"]["split_words"]["word_index"]): _shape(
            json.loads(row["content"]["merge_votes"]["seen"])
        )
        for row in _rows(root, "merge_votes")
        if "seen" in (row["content"].get("merge_votes") or {})
    }


def test_a_tool_merge_is_not_given_the_fields_its_drop_names(project):
    _configure(project, ONLINE_MERGE)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh", env=_env())

    assert result.returncode == 0, result.stdout + result.stderr
    seen = _seen_by_the_merge(project)
    assert len(seen) == 6
    assert all(given == KEPT for given in seen.values()), seen


def test_a_retried_merge_is_not_given_the_fields_its_drop_names(project):
    _configure(project, ONLINE_MERGE)
    (project / FAULT).write_text(json.dumps({"item": "beta"}))
    first = run_agac(project, "run", "-a", WORKFLOW, "--fresh", env=_env())
    assert "beta/0" not in _seen_by_the_merge(project), first.stdout + first.stderr
    (project / FAULT).unlink()

    result = run_agac(project, "retry", "-a", WORKFLOW, env=_env())

    assert result.returncode == 0, result.stdout + result.stderr
    seen = _seen_by_the_merge(project)
    assert {"beta/0", "beta/1"} <= set(seen)
    assert all(given == KEPT for given in seen.values()), seen


def test_a_batch_merge_does_not_send_the_fields_its_drop_names(project):
    _configure(project, BATCH_MERGE)
    env = {**_env(), "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "999"}

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh", env=env)

    held = list((project / ".agac" / "batch_state").glob("*.json"))
    assert len(held) == 1, result.stdout + result.stderr
    tasks = json.loads(held[0].read_text())["tasks"]
    assert len(tasks) == 6
    sent = [_shape(json.loads(task["user_content"])) for task in tasks]
    assert all(given == KEPT for given in sent), sent
