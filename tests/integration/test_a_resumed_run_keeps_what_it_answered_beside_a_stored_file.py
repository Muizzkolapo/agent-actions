"""A run resumed beside a file stored before keeps what the interrupted run answered (1273).

An action edited after it completed is run again with ``--rerun``, which answers part of a
file and is stopped. Each record it answered has a checkpoint row beside the file stored before
the edit, and the run after that kept the record's `success` but asked the model again:
the stored row is older than the answer and the checkpoint row had not been enriched, so
neither was carried. Every record the stopped run answered was paid for twice.

The checkpoint row is now finished as the answer it was, enriched and collected with the
run's own, in place of the stored row. The row stored before the edit is never carried.

Every run is an `agac run` through the CLI, executor, store and the action's own tool or
the mock provider. Only the interrupt is stood in for.
"""

import csv
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration import (
    test_a_stopped_action_keeps_only_what_its_config_still_answers as summarizing,
)
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    online,  # noqa: F401
    project,  # noqa: F401
    provider,  # noqa: F401
)

SOURCE = Path(__file__).parents[2] / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
ACTION = "tag"
READER = "read"
ITEMS = ["a0", "a1", "a2", "a3"]
STOP_AT = "AGAC_TEST_STOP_AT"
ANSWER = "AGAC_TEST_ANSWER"
TWICE = "AGAC_TEST_TWICE"

HEAD = """name: map_reduce_fanin_check
description: "An action tagging each staged item, and its reader"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  data_source:
    type: local
    folder: ./staging
    file_type: [json, csv]

actions:
"""

STAGE = """  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope:
      observe: [source.*]

"""

TAG_FIRST = f"""  - name: {ACTION}
    kind: tool
    impl: tag_staged
    intent: "Tag each item"
    schema: {{ tag: string }}
    context_scope:
      observe: [source.*]

"""

TAG_BELOW = f"""  - name: {ACTION}
    kind: tool
    impl: tag_upstream
    dependencies: [stage_items]
    intent: "Tag each item"
    schema: {{ tag: string }}
    context_scope:
      observe: [stage_items.*]

"""

READ = f"""  - name: {READER}
    kind: tool
    impl: read_each_tag
    dependencies: [{ACTION}]
    intent: "Read each tag"
    schema: {{ seen: string }}
    context_scope:
      observe: [{ACTION}.*]
"""

# Named apart from the other tests' tools: discovery keeps a tool module by its name.
# Logs each item it is asked for, so a test can tell what a run asked again; its answer
# carries the run's mark, so a test can tell an answer from before the edit.
TOOLS = f"""import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


def _tag(item: str) -> list[dict[str, Any]]:
    if os.environ.get("{STOP_AT}") == item:
        raise KeyboardInterrupt()
    with Path("asked.txt").open("a") as asked:
        asked.write(item + "\\n")
    tag = f"{{item}}@{{os.environ.get('{ANSWER}', '')}}"
    if os.environ.get("{TWICE}") == item:
        return [{{"tag": f"{{tag}}-1"}}, {{"tag": f"{{tag}}-2"}}]
    return [{{"tag": tag}}]


@udf_tool()
def tag_staged(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _tag(str((data.get("source") or {{}}).get("item_id", "")))


@udf_tool()
def tag_upstream(data: dict[str, Any]) -> list[dict[str, Any]]:
    return _tag(str((data.get("stage_items") or {{}}).get("item_id", "")))


@udf_tool()
def read_each_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {{"seen": (data.get("{ACTION}") or {{}}).get("tag", "")}}
"""

GUARD = "    guard: { condition: 'true', on_false: \"skip\" }\n"


def _project(tmp_path, monkeypatch, *, first_stage: bool, staged_as: str) -> Path:
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    config = HEAD + ("" if first_stage else STAGE) + (TAG_FIRST if first_stage else TAG_BELOW)
    _config(root).write_text(config + READ)
    (root / "tools" / WORKFLOW / "fix1273_tag_tools.py").write_text(TOOLS)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging)
    path = staging / staged_as
    path.parent.mkdir(parents=True)
    if path.suffix == ".csv":
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["item_id", "text"])
            writer.writerows([item, f"text of {item}"] for item in ITEMS)
    else:
        path.write_text(json.dumps([{"item_id": i, "text": f"text of {i}"} for i in ITEMS]))
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv(STOP_AT, raising=False)
    monkeypatch.delenv(TWICE, raising=False)
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _run(*args):
    return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])


def _status(root, action=ACTION):
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[action]["status"]


def _asked(root):
    asked = root / "asked.txt"
    items = asked.read_text().split() if asked.exists() else []
    asked.unlink(missing_ok=True)
    return sorted(items)


def _stored(root, action):
    from agent_actions.config.project_paths import ProjectPathsFactory
    from agent_actions.storage import get_storage_backend

    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return {
            path: backend._read_target_raw(action, path)
            for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def _rows(root, action):
    return [row for rows in _stored(root, action).values() for row in rows]


def _field(row, action, key):
    return ((row.get("content") or {}).get(action) or {}).get(key)


def _transitions(row, action):
    return [entry["to"] for entry in row.get("_state_history") or [] if entry["action"] == action]


def _comparable(row):
    """What an answer's row holds once stored, without what names this run's own write."""
    return {
        "keys": sorted(set(row) - {"_state_history"}),
        "lineage": len(row.get("lineage") or []),
        "metadata": row.get("metadata"),
        "parent": bool(row.get("parent_target_id")),
        "root": bool(row.get("root_target_id")),
        "state": row.get("_state"),
        "transitions": _transitions(row, ACTION),
    }


def _edited_then_stopped_at_a2(root, monkeypatch):
    """Stores the file, adds a guard, and reruns the action under the edit until the tool
    is stopped on a2, having answered a0 and a1 beside the file stored before."""
    monkeypatch.setenv(ANSWER, "before")
    first = _run("--fresh")
    assert first.exit_code == 0, first.output
    assert _asked(root) == ITEMS
    config = _config(root)
    text = config.read_text()
    edited = text.replace('    intent: "Tag each item"\n', '    intent: "Tag each item"\n' + GUARD)
    assert edited != text
    config.write_text(edited)
    monkeypatch.setenv(ANSWER, "after")
    monkeypatch.setenv(STOP_AT, "a2")
    _run("--rerun", ACTION)
    monkeypatch.delenv(STOP_AT)
    assert _status(root) == "interrupted"
    assert _asked(root) == ["a0", "a1"]


@pytest.mark.parametrize("staged_as", ["items.json", "sub/items.json", "items.csv"])
@pytest.mark.parametrize("first_stage", [True, False], ids=["first-action", "below-the-first"])
def test_a_resume_asks_only_what_the_stopped_run_never_answered(
    tmp_path, monkeypatch, first_stage, staged_as
):
    root = _project(tmp_path, monkeypatch, first_stage=first_stage, staged_as=staged_as)
    _edited_then_stopped_at_a2(root, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _asked(root) == ["a2", "a3"], "answers the stopped run gave were paid for again"
    assert _status(root) == "completed"
    stored = _stored(root, ACTION)
    assert list(stored) == [str(Path(staged_as).with_suffix(".json"))]
    tags = sorted(_field(row, ACTION, "tag") for row in _rows(root, ACTION))
    assert tags == [f"{item}@after" for item in ITEMS], "a row from before the edit"
    assert sorted(_field(row, READER, "seen") for row in _rows(root, READER)) == tags


@pytest.mark.parametrize("first_stage", [True, False], ids=["first-action", "below-the-first"])
def test_a_record_carried_from_its_checkpoint_is_stored_as_one_the_run_answered(
    tmp_path, monkeypatch, first_stage
):
    """a0 and a1 come from their checkpoint rows, a2 and a3 from the tool: all four rows
    get the same lineage, metadata, parent, root and state, and the reader builds on them."""
    root = _project(tmp_path, monkeypatch, first_stage=first_stage, staged_as="items.json")
    _edited_then_stopped_at_a2(root, monkeypatch)

    assert _run().exit_code == 0

    rows = {_field(row, ACTION, "tag"): row for row in _rows(root, ACTION)}
    assert len(rows) == len(ITEMS)
    answered = _comparable(rows["a3@after"])
    assert answered["transitions"] == ["processed"]
    assert answered["metadata"] == {
        "model": "tag_staged" if first_stage else "tag_upstream",
        "provider": "tool",
    }
    for tag in ("a0@after", "a1@after", "a2@after"):
        assert _comparable(rows[tag]) == answered, tag
    upstream = {}
    if not first_stage:
        upstream = {row["source_guid"]: row for row in _rows(root, "stage_items")}
    for row in rows.values():
        if upstream:
            item = upstream[row["source_guid"]]
            assert row["lineage"] == [*item["lineage"], row["node_id"]]
            assert row["parent_target_id"] == item["target_id"]
        else:
            assert row["lineage"] == [row["node_id"]]
    tags = {row["source_guid"]: row for row in rows.values()}
    for row in _rows(root, READER):
        assert row["lineage"] == [*tags[row["source_guid"]]["lineage"], row["node_id"]]


@pytest.mark.parametrize("first_stage", [True, False], ids=["first-action", "below-the-first"])
def test_a_record_the_stopped_run_answered_with_several_rows_is_asked_again(
    tmp_path, monkeypatch, first_stage
):
    """Its checkpoint rows share its identity until enrichment gives each its own, so they
    cannot stand as they are; its rows stored before the edit are not kept either."""
    root = _project(tmp_path, monkeypatch, first_stage=first_stage, staged_as="items.json")
    monkeypatch.setenv(TWICE, "a0")
    _edited_then_stopped_at_a2(root, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _asked(root) == ["a0", "a2", "a3"]
    tags = sorted(_field(row, ACTION, "tag") for row in _rows(root, ACTION))
    assert tags == ["a0@after-1", "a0@after-2", "a1@after", "a2@after", "a3@after"]
    assert sorted(_field(row, READER, "seen") for row in _rows(root, READER)) == tags


def test_the_run_after_the_resume_asks_nothing(tmp_path, monkeypatch):
    root = _project(tmp_path, monkeypatch, first_stage=False, staged_as="items.json")
    _edited_then_stopped_at_a2(root, monkeypatch)
    assert _run().exit_code == 0
    _asked(root)
    before = _stored(root, ACTION)

    result = _run()

    assert result.exit_code == 0, result.output
    assert _asked(root) == []
    assert _stored(root, ACTION) == before


def _page(row):
    return ((row.get("content") or {}).get("source") or {}).get("page_content")


def test_a_resumed_llm_action_asks_only_what_the_stopped_run_never_answered(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The prompt is edited after both files are stored. The --rerun after it answers alpha
    and is stopped on beta, in pages1.json. The resume asks for the other three alone, and alpha's
    row is the answer to the edited prompt, enriched as the others are."""
    provider.answers()
    assert summarizing._run("--fresh").exit_code == 0
    before_the_edit = summarizing._stored(online)
    summarizing._edit_prompt(online)
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    summarizing._run("--rerun", summarizing.ACTION)
    assert summarizing._status(online) == "interrupted"
    provider.answers()

    result = summarizing._run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == ["Page beta.", "Page delta.", "Page gamma."]
    after = summarizing._stored(online)
    assert sorted(after) == sorted(before_the_edit)
    assert summarizing._still_holding(before_the_edit, after) == [], "a row from before the edit"
    rows = summarizing._stored_rows(online)
    assert sorted(_page(row) for row in rows) == summarizing.EVERY_PAGE
    metadata = {"model": summarizing.MODEL, "provider": "agac-provider"}
    keys = {_page(row): sorted(set(row) - {"_state_history"}) for row in rows}
    for row in rows:
        page = _page(row)
        assert row.get("lineage") == [row["node_id"]], page
        assert row.get("metadata") == metadata, page
        assert row.get("_state") == "processed", page
        assert [
            entry["to"]
            for entry in row.get("_state_history") or []
            if entry["action"] == summarizing.ACTION
        ] == ["processed"], page
        assert keys[page] == keys["Page delta."], page


def _switch(root, to):
    config = summarizing._config(root)
    text = config.read_text()
    switched = text.replace(
        "run_mode: online" if to == "batch" else "run_mode: batch", f"run_mode: {to}"
    )
    assert switched != text
    config.write_text(switched)


def _submit_and_collect():
    first, second = summarizing._run(), summarizing._run()
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output


def test_an_action_switched_to_batch_beside_a_file_stored_before_its_edit_keeps_none_of_it(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """Alpha is answered online by the --rerun after the edit and the run is stopped. Batch does not
    finish a checkpoint row, so it sends alpha again, rather than call it done and carry
    the row pages1.json held from before the edit."""
    provider.answers()
    assert summarizing._run("--fresh").exit_code == 0
    before_the_edit = summarizing._stored(online)
    summarizing._edit_prompt(online)
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    summarizing._run("--rerun", summarizing.ACTION)
    assert summarizing._status(online) == "interrupted"
    provider.answers()
    _switch(online, "batch")
    sent_before = summarizing._sent(online)

    _submit_and_collect()

    assert [page for page, _ in summarizing._sent_since(online, sent_before)] == sorted(
        summarizing.EVERY_PAGE
    )
    after = summarizing._stored(online)
    assert sorted(after) == sorted(before_the_edit)
    assert summarizing._still_holding(before_the_edit, after) == [], "a row from before the edit"
    assert len(summarizing._stored_rows(online)) == len(summarizing.EVERY_PAGE)


def test_a_file_stored_by_batch_leaves_no_checkpoint_row_an_online_run_takes_for_newer(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """Stopped online on beta, having answered alpha and stored nothing, the action is
    switched to batch. Batch sends all four pages, stores pages1.json, and is stopped
    collecting pages2.json. Switched back, the online run asks for gamma and delta alone
    and keeps what batch stored for pages1.json: alpha's checkpoint row is older."""
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    summarizing._run("--fresh")
    assert summarizing._status(online) == "interrupted"
    provider.answers()
    _switch(online, "batch")
    assert summarizing._run().exit_code == 0
    with summarizing._collecting_fails_on("pages2.json"):
        assert summarizing._run().exit_code != 0
    assert summarizing._status(online) == "failed"
    stored_by_batch = _rows_of(online, "pages1.json")
    assert sorted(_page(row) for row in stored_by_batch) == ["Page alpha.", "Page beta."]
    _switch(online, "online")

    result = summarizing._run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == ["Page delta.", "Page gamma."]
    assert _rows_of(online, "pages1.json") == stored_by_batch
    assert summarizing._status(online) == "completed"


def _rows_of(root, path):
    backend = summarizing._backend(root)
    try:
        return backend._read_target_raw(summarizing.ACTION, path)
    finally:
        backend.close()
