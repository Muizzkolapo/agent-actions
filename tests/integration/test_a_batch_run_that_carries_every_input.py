"""A batch run whose every input is already done writes its file for those inputs.

Nothing is sent and nothing is finalized, so the file was left as it stood: rows for
records that had left it stayed, where online writes the file again every run. A record
that moved to another file was answered there and still held here, twice in all.

Later-stage tests drive the real pipeline, store, registry and collect pass, and only the
provider is fake; first-stage tests drive ``process_initial_stage``. The CLI tests run
`agac run` against the provider mock as a user meets it: resuming a run that died, and
running again after an edit.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.batch.infrastructure.context import batch_output_name
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_batch_run_with_nothing_to_send_is_collected import _status
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import _Action
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    FIRST,
    _run,
    _run_to_the_end,
    _statuses,
)
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    Answerer,
    _Batch,
    _FirstStageBatch,
    rec,
)
from tests.integration.test_retry_selection_under_batch import WORKFLOW, _backend, _project


@pytest.fixture(autouse=True)
def _only_warnings_are_captured(caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions")


def _writes_to(backend: Any, name: str):
    """Watch the store for writes of *name*; the list fills as they happen."""
    written: list[int] = []
    write = backend.write_target

    def watching(action: str, path: str, rows: list[dict[str, Any]]) -> Any:
        if (action, path) == (ACTION, name):
            written.append(len(rows))
        return write(action, path, rows)

    return written, patch.object(backend, "write_target", watching)


def test_a_record_that_moves_to_another_file_is_held_only_in_that_one(tmp_path):
    """a2 is answered in page2, its new file, and page1 has nothing left to send."""
    action = _Action(tmp_path)
    action.run(
        {
            "page1.json": [rec("a1", keep=True), rec("a2", keep=True)],
            "page2.json": [rec("b1", keep=True)],
        }
    )

    action.run(
        {
            "page1.json": [rec("a1", keep=True)],
            "page2.json": [rec("b1", keep=True), rec("a2", keep=True)],
        }
    )

    assert action.files() == {
        "page1.json": ["processed:a1@batch-1"],
        "page2.json": ["processed:a2@batch-3", "processed:b1@batch-2"],
    }


def test_rows_a_record_limit_holds_back_stay_while_a_record_that_left_goes(tmp_path):
    """a3 is held back by the limit and is still an input; a4 is no longer one."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2"), rec("a3"), rec("a4")])

    held = batch.run(2, [rec("a1"), rec("a2"), rec("a3")], extra={"record_limit": 2})

    assert batch.sent[1] == []
    assert held == ["processed:a1:0@run1", "processed:a2:0@run1", "processed:a3:0@run1"]


def test_a_file_in_a_subdirectory_drops_the_row_under_its_one_name(tmp_path):
    batch = _Batch(tmp_path, "sub/page.json")
    batch.run(1, [rec("a1"), rec("a2")])

    held = batch.run(2, [rec("a1")])

    assert held == ["processed:a1:0@run1"]
    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]


def test_a_first_stage_record_that_leaves_staging_takes_its_row_with_it(tmp_path):
    batch = _FirstStageBatch(tmp_path)
    batch.run(1, [{"item": "x1"}, {"item": "x2"}], {})

    held = batch.run(2, [{"item": "x1"}], {})

    assert batch.sent == [["x1", "x2"], []]
    assert held == ["processed:x1:0@run1"]


def test_an_action_whose_every_input_is_done_completes_as_before(tmp_path):
    """Writing the file is not a node-level passthrough: with that, an action holding
    no row reads skipped, and the batch check reports a passthrough."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2")])

    batch.run(2, [rec("a1")])

    assert batch.raised == [None, None]
    assert batch.backend.get_disposition(ACTION, record_id=NODE_LEVEL_RECORD_ID) == []
    assert _status(batch.backend) == ActionStatus.COMPLETED


def test_a_file_that_would_be_written_as_it_stands_is_not_written(tmp_path):
    """The common resume: every input done, none gone. Rewriting it re-stores every row."""
    batch = _Batch(tmp_path)
    first = batch.run(1, [rec("a1"), rec("a2")])
    written, watching = _writes_to(batch.backend, batch_output_name("page.json"))

    with watching:
        held = batch.run(2, [rec("a1"), rec("a2")])

    assert (held, written, batch.raised[-1]) == (first, [], None)


def test_a_repair_that_names_no_record_of_the_file_leaves_it_as_it_stands(tmp_path):
    """A repair answers what it named, and online carries every other stored row, the
    failure of a record absent from the file included."""
    batch = _Batch(tmp_path)
    first = batch.run(1, [rec("a1"), rec("a2"), rec("a3")], Answerer({"a2": "fail"}))
    written, watching = _writes_to(batch.backend, batch_output_name("page.json"))

    with watching:
        held = batch.run(2, [rec("a1"), rec("a3")], retry=["a2"])

    assert batch.sent[-1] == []
    assert (held, written, batch.raised[-1]) == (first, [], None)


# ── through `agac run` ────────────────────────────────────────────────────────

STAGING = ("agent_workflow", WORKFLOW, "agent_io", "staging")
P1 = {"page_id": "p1", "page_content": "dbt models are SELECT statements."}
P2 = {"page_id": "p2", "page_content": "Materializations control how each model is built."}
P3 = {"page_id": "p3", "page_content": "Incremental models only process new rows."}
P4 = {"page_id": "p4", "page_content": "Seeds are CSV files."}


def _stage(project, **files: list[dict[str, Any]]) -> None:
    staging = project.joinpath(*STAGING)
    for stale in staging.glob("*.json"):
        stale.unlink()
    for name, records in files.items():
        staging.joinpath(f"{name}.json").write_text(json.dumps(records))


def _pages(project) -> dict[str, list[str]]:
    """The page ids each stored file of the action holds."""
    backend = _backend(project)
    try:
        return {
            path: sorted(
                row["content"]["source"]["page_id"] for row in backend.read_target(FIRST, path)
            )
            for path in backend.list_target_files(FIRST)
        }
    finally:
        backend.close()


def _died_while_running(project) -> None:
    """What a run that died part-way leaves: the action recorded as running."""
    (status_file,) = project.joinpath("agent_workflow", WORKFLOW).rglob("*status*.json")
    statuses = json.loads(status_file.read_text())
    statuses[FIRST]["status"] = ActionStatus.RUNNING.value
    status_file.write_text(json.dumps(statuses))


@pytest.fixture
def two_pages_collected(tmp_path):
    root = _project(tmp_path)
    _stage(root, pages1=[P1, P2], pages2=[P3])
    assert "run again" in _run(root, "--fresh"), "the fixture did not pause on submission"
    _run_to_the_end(root)
    assert _pages(root) == {"pages1.json": ["p1", "p2"], "pages2.json": ["p3"]}
    return root


def test_a_record_moved_between_staged_files_is_held_once_after_a_resume(two_pages_collected):
    project = two_pages_collected
    _stage(project, pages1=[P1], pages2=[P3, P2])
    _died_while_running(project)

    transcript = _run_to_the_end(project)

    assert _pages(project) == {"pages1.json": ["p1"], "pages2.json": ["p2", "p3"]}, transcript
    assert _statuses(project) == {FIRST: ActionStatus.COMPLETED.value}


def test_a_staged_file_emptied_before_a_prompt_edit_holds_nothing(two_pages_collected):
    """Unedited, a complete action does not run again. The edit resets it, which keeps
    what it stored, and online then writes the emptied file as it is."""
    project = two_pages_collected
    _stage(project, pages1=[], pages2=[P3, P4])
    prompts = project / "prompt_store" / "p.md"
    anchor = "{prompt Summarize}"
    assert anchor in prompts.read_text()
    prompts.write_text(prompts.read_text().replace(anchor, anchor + "\nBe brief.", 1))

    transcript = _run_to_the_end(project)

    assert _pages(project) == {"pages1.json": [], "pages2.json": ["p3", "p4"]}, transcript
