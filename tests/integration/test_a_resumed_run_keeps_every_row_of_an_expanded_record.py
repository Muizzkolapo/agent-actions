"""A run resumed from a checkpoint keeps every row of a record that expanded (1263).

An action interrupted on its first run has stored nothing, only the checkpoint rows of
the records it finished, and the next run carries those records from them. A record the
action answered with several rows left one: its rows share the record's identity until
enrichment gives each its own, and each one checkpointed replaced the one before. The
resumed run stored that last row alone and recorded the action complete.

Every run is an `agac run` through the CLI, executor, store and the action's own tool.
Only the interrupt is stood in for, raised by the tool at the record it is told to stop
on.
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
ACTION = "right"
READER = "right_reader"
STOP_AT = "AGAC_TEST_STOP_AT"
ONE_ROW = "AGAC_TEST_ONE_ROW"

CONFIG = f"""name: {WORKFLOW}
description: "An action answering each item with rows of its own, and its reader"
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
    schema: {{ item_id: string, text: string }}
    context_scope:
      observe: [source.item_id, source.text]

  - name: {ACTION}
    kind: tool
    impl: tag_item
    dependencies: [stage_items]
    intent: "Tag each item, twice where it is told to"
    schema: {{ tag: string }}
    context_scope:
      observe: [stage_items.*]

  - name: {READER}
    kind: tool
    impl: read_tag
    dependencies: [{ACTION}]
    intent: "Read each tag"
    schema: {{ seen: string }}
    context_scope:
      observe: [{ACTION}.*]
"""

# The same action run first, on the staged items, which the staging pipeline runs.
FIRST_STAGE_CONFIG = f"""name: {WORKFLOW}
description: "A first action answering each item with rows of its own, and its reader"
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
  - name: {ACTION}
    kind: tool
    impl: tag_source
    intent: "Tag each item, twice where it is told to"
    schema: {{ tag: string }}
    context_scope:
      observe: [source.item_id]

  - name: {READER}
    kind: tool
    impl: read_tag
    dependencies: [{ACTION}]
    intent: "Read each tag"
    schema: {{ seen: string }}
    context_scope:
      observe: [{ACTION}.*]
"""

# Logs each item it is asked for, so a test can tell what a run asked again.
TOOLS = f"""import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


def _tagged(item: str) -> list[dict[str, Any]]:
    if os.environ.get("{STOP_AT}") == item:
        raise KeyboardInterrupt()
    with Path("asked.txt").open("a") as asked:
        asked.write(item + "\\n")
    if os.environ.get("{ONE_ROW}") == item:
        return [{{"tag": item}}]
    return [{{"tag": f"{{item}}-a"}}, {{"tag": f"{{item}}-b"}}]


@udf_tool()
def tag_item(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _tagged((data.get("stage_items") or {{}}).get("item_id", ""))


@udf_tool()
def tag_source(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _tagged((data.get("source") or {{}}).get("item_id", ""))


@udf_tool()
def read_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {{"seen": (data.get("{ACTION}") or {{}}).get("tag", "")}}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Three items, alpha, beta and gamma, each tagged twice unless the test says once."""
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG)
    (root / "tools" / WORKFLOW / "tag_tools.py").write_text(TOOLS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv(STOP_AT, raising=False)
    monkeypatch.delenv(ONE_ROW, raising=False)
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _interrupted_at_gamma(root, monkeypatch):
    """A first run stopped on gamma, having finished alpha and beta and stored nothing."""
    monkeypatch.setenv(STOP_AT, "gamma")
    _run("--fresh")
    monkeypatch.delenv(STOP_AT)
    assert _status(root) == "interrupted"
    assert _stored(root, ACTION) == []
    (root / "asked.txt").unlink()


def _status(root, action=ACTION):
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


def _store(root):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _stored(root, action):
    backend = _store(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend._read_target_raw(action, path)
        ]
    finally:
        backend.close()


def _as_an_earlier_version_left_it(root):
    """That version saved a record's rows one at a time under the identity they share, so
    the last of them was the one kept, as the record itself rather than a list."""
    backend = _store(root)
    try:
        stored = backend.connection.execute(
            "SELECT id, record_data FROM checkpoint_output"
        ).fetchall()
        assert stored, "the interrupted run checkpointed nothing"
        for row_id, answer in stored:
            backend.connection.execute(
                "UPDATE checkpoint_output SET record_data = ? WHERE id = ?",
                (json.dumps(json.loads(answer)[-1]), row_id),
            )
        backend.connection.commit()
    finally:
        backend.close()


def _tags(rows):
    return sorted(((row.get("content") or {}).get(ACTION) or {}).get("tag") for row in rows)


def _seen(rows):
    return sorted(((row.get("content") or {}).get(READER) or {}).get("seen") for row in rows)


def _asked(root):
    return sorted((root / "asked.txt").read_text().split())


def test_a_resumed_run_stores_every_row_of_the_records_its_checkpoint_holds(project, monkeypatch):
    _interrupted_at_gamma(project, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed"
    rows = _stored(project, ACTION)
    assert _tags(rows) == ["alpha-a", "alpha-b", "beta-a", "beta-b", "gamma-a", "gamma-b"]
    assert len({row["source_guid"] for row in rows}) == len(rows), "rows share an identity"
    assert _seen(_stored(project, READER)) == _tags(rows)


def test_a_record_answered_with_several_rows_is_asked_again_and_one_with_a_row_is_carried(
    project, monkeypatch
):
    """A checkpoint row is saved before enrichment gives an expansion's rows identities of
    their own, so those rows cannot be carried as they are, and the record is asked again.
    A record that answered with one row is carried, as before."""
    monkeypatch.setenv(ONE_ROW, "beta")
    _interrupted_at_gamma(project, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _tags(_stored(project, ACTION)) == ["alpha-a", "alpha-b", "beta", "gamma-a", "gamma-b"]
    assert _asked(project) == ["alpha", "gamma"]


def test_a_resumed_first_action_stores_every_row_of_the_records_its_checkpoint_holds(
    project, monkeypatch
):
    """The staging pipeline runs a workflow's first action, a route of its own to the
    checkpoint the carry reads."""
    (project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml").write_text(
        FIRST_STAGE_CONFIG
    )
    _interrupted_at_gamma(project, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed"
    rows = _stored(project, ACTION)
    assert _tags(rows) == ["alpha-a", "alpha-b", "beta-a", "beta-b", "gamma-a", "gamma-b"]
    assert len({row["source_guid"] for row in rows}) == len(rows), "rows share an identity"
    assert _seen(_stored(project, READER)) == _tags(rows)


def test_a_run_an_earlier_version_stopped_asks_again_for_the_records_it_checkpointed(
    project, monkeypatch
):
    """That version's checkpoint row is one row of its record, which cannot say whether
    the record had others: carried, it would be stored alone in place of all of them."""
    _interrupted_at_gamma(project, monkeypatch)
    _as_an_earlier_version_left_it(project)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _status(project) == "completed"
    rows = _stored(project, ACTION)
    assert _tags(rows) == ["alpha-a", "alpha-b", "beta-a", "beta-b", "gamma-a", "gamma-b"]
    assert len({row["source_guid"] for row in rows}) == len(rows), "rows share an identity"
    assert _asked(project) == ["alpha", "beta", "gamma"]
