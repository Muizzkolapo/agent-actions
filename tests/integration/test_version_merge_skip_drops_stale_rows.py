"""A version merge skipped because its versions hold nothing holds nothing either (1230).

Two roads lead a merge to a skip: a version that is itself skipped trips the
circuit breaker, and versions that completed with no rows raise
AllVersionsFilteredError. Neither rewrites the merge's output, so rows it stored
before must be removed by the skip — or they outlive the output they merged.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parents[2] / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
ITEMS = 3

CONFIG = """name: map_reduce_fanin_check
description: "version merge skip"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
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

  - name: recap
    kind: tool
    impl: note_direct
    dependencies: [merge_direct]
    intent: "Read the merge"
    schema: { note: string }
    context_scope:
      observe: [merge_direct.*]
"""

RESET = "{ condition: 'true', on_false: \"skip\" }"


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _staging(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "items.json"


def _add_guard(root, impl, guard):
    config = _config(root)
    config.write_text(
        config.read_text().replace(f"    impl: {impl}\n", f"    impl: {impl}\n    guard: {guard}\n")
    )


def _reset_readers(root):
    _add_guard(root, "merge_votes", RESET)
    _add_guard(root, "note_direct", RESET)


def _rows(root, action):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return sum(
            len(backend._read_target_raw(action, path))
            for path in backend.list_target_files(action)
        )
    finally:
        backend.close()


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
    assert result.exit_code == 0, result.output
    return result


@pytest.fixture
def merged(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    _config(root).write_text(CONFIG)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    _run("--fresh")
    assert _rows(root, "merge_direct") == ITEMS
    assert _rows(root, "recap") == ITEMS
    return root


def test_every_version_filtered_leaves_the_merge_and_its_reader_empty(merged):
    _add_guard(
        merged,
        "cast_vote_direct",
        '{ condition: \'stage_items.item_id == "none"\', on_false: "filter" }',
    )
    _reset_readers(merged)

    result = _run()

    assert "Upstream dependency 'vote_direct_" in result.output, result.output
    assert _rows(merged, "merge_direct") == 0
    assert _rows(merged, "recap") == 0


def test_one_version_filtered_leaves_the_merge_empty(merged):
    _add_guard(
        merged,
        "cast_vote_direct",
        '{ condition: \'${voter_id} > 1 AND stage_items.item_id != "none"\', on_false: "filter" }',
    )
    _reset_readers(merged)

    result = _run()

    assert "Upstream dependency 'vote_direct_1' skipped" in result.output, result.output
    assert _rows(merged, "vote_direct_2") == ITEMS
    assert _rows(merged, "merge_direct") == 0


def test_versions_that_completed_empty_leave_the_merge_and_its_reader_empty(merged):
    _staging(merged).write_text(json.dumps([]))
    for impl in ("stage_items", "cast_vote_direct"):
        _add_guard(merged, impl, RESET)
    _reset_readers(merged)

    result = _run()

    assert "all_versions_filtered" in result.output, result.output
    assert _rows(merged, "vote_direct_1") == 0
    assert _rows(merged, "merge_direct") == 0
    assert _rows(merged, "recap") == 0


def test_versions_that_completed_empty_then_refilled_merge_again(merged):
    original = _staging(merged).read_text()
    _staging(merged).write_text(json.dumps([]))
    for impl in ("stage_items", "cast_vote_direct"):
        _add_guard(merged, impl, RESET)
    _reset_readers(merged)
    _run()
    _run()
    assert _rows(merged, "merge_direct") == 0

    _staging(merged).write_text(original)
    config = _config(merged)
    config.write_text(
        "".join(line for line in config.read_text().splitlines(True) if "guard:" not in line)
    )
    _run()

    assert _rows(merged, "merge_direct") == ITEMS
    assert _rows(merged, "recap") == ITEMS
