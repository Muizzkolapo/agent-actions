"""An action whose guard filters every record of one file is not skipped (1253).

Online, each input file reaches the guard on its own, and a file whose every
record was filtered wrote the node-level `skipped` row. That row names the action,
not the file, and the executor reads it first: the action read skipped though its
other file had just written rows, and its readers were skipped over those rows.
Batch writes a node-level `passthrough` instead and reads skipped only while the
action holds no row, so the same project completed there.

A reader's input for the wholly filtered file is then empty. Online stores that
file empty; batch sent nothing for it and kept what it had stored there before.

Editing the action is what resets it; its readers are reset by that.
"""

import json

import pytest

from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    ANCHOR,
    FIRST,
    READER,
    READER_ACTION,
    _config,
    _run_to_the_end,
    _statuses,
)
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    _run as _run_in_its_own_process,
)
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _backend,
    chained,  # noqa: F401
    project,  # noqa: F401
)
from tests.integration.test_retry_selection_under_batch import _backend as _model_backend
from tests.integration.test_retry_selection_under_batch import _project
from tests.integration.test_skipped_reader_drops_stale_rows import (
    FILTER_ALL,
    MODES,
    _add_guard_to,
    _run,
    _status,
)

OTHER = 3
KEEP_OTHER = '{ condition: \'source.page_content LIKE "other%"\', on_false: "filter" }'


def _staging(root, workflow=WORKFLOW):
    return root / "agent_workflow" / workflow / "agent_io" / "staging"


def _rows_by_file(root, action, open_store=_backend):
    backend = open_store(root)
    try:
        return {
            path: len(backend._read_target_raw(action, path))
            for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def _node_skipped(root, action):
    backend = _backend(root)
    try:
        return backend.has_disposition(action, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID)
    finally:
        backend.close()


def _give_it_a_second_file(root, last):
    _staging(root).joinpath("other.json").write_text(
        json.dumps([{"page_content": f"other {i}"} for i in range(OTHER)])
    )
    _run("--fresh")
    assert _rows_by_file(root, last) == {"other.json": OTHER, "pages.json": RECORDS}
    return root


@pytest.fixture
def two_files(chained):  # noqa: F811
    return _give_it_a_second_file(chained, SECOND)


@pytest.fixture
def two_files_no_reader(project):  # noqa: F811
    return _give_it_a_second_file(project, ACTION)


@MODES
def test_an_action_whose_guard_filters_one_whole_file_completes_and_its_reader_runs(
    two_files, mode
):
    _add_guard_to(two_files, ACTION, KEEP_OTHER)

    _run("-e", mode)

    assert _rows_by_file(two_files, ACTION) == {"other.json": OTHER, "pages.json": 0}
    assert _status(two_files, ACTION) == "completed"
    assert _status(two_files, SECOND) == "completed"
    # It ran on what the action holds now, so no row of it is built from a filtered record.
    assert _rows_by_file(two_files, SECOND) == {"other.json": OTHER, "pages.json": 0}


def test_the_skip_one_file_wrote_is_not_left_to_describe_the_action(two_files_no_reader):
    """Left behind, `agac dispositions` shows a completed action as skipped, and the
    next run reads it as a skip from before and runs the action again. Without a
    reader, nothing else clears it."""
    _add_guard_to(two_files_no_reader, ACTION, KEEP_OTHER)
    _run()

    assert _status(two_files_no_reader, ACTION) == "completed"
    assert not _node_skipped(two_files_no_reader, ACTION)
    assert f"{ACTION} — already complete" in _run().output


def test_an_action_whose_guard_filters_every_file_is_still_skipped(two_files):
    """The other half of the rule: holding no row, the action is skipped, and its
    reader is skipped under it and emptied."""
    _add_guard_to(two_files, ACTION, FILTER_ALL)

    _run()

    assert _status(two_files, ACTION) == "skipped"
    assert _status(two_files, SECOND) == "skipped"
    assert _rows_by_file(two_files, ACTION) == {"other.json": 0, "pages.json": 0}
    assert sum(_rows_by_file(two_files, SECOND).values()) == 0


def _model_project_whose_guard_now_filters_one_whole_file(tmp_path, run_mode):
    """`summarize` read by `publish`, run to the end over two files, then given a guard
    that filters every record of `pages.json`."""
    root = _project(tmp_path)
    staging = _staging(root, "batch_field_rules")
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(3)])
    )
    staging.joinpath("other.json").write_text(
        json.dumps([{"page_id": f"o{i}", "page_content": f"other {i}"} for i in range(2)])
    )
    config = _config(root)
    text = config.read_text().replace("run_mode: batch", f"run_mode: {run_mode}")
    config.write_text(text.rstrip("\n") + "\n" + READER_ACTION)
    _run_in_its_own_process(root, "--fresh")
    _run_to_the_end(root)
    assert _rows_by_file(root, READER, _model_backend) == {"other.json": 2, "pages.json": 3}

    config.write_text(config.read_text().replace(ANCHOR, f"{ANCHOR}    guard: {KEEP_OTHER}\n", 1))
    return root


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_model_action_whose_guard_filters_one_whole_file_completes_in_either_run_mode(
    tmp_path, run_mode
):
    """The measured case: an LLM action against the provider mock, where batch
    already completed and online did not."""
    root = _model_project_whose_guard_now_filters_one_whole_file(tmp_path, run_mode)

    transcript = _run_to_the_end(root)

    assert _statuses(root) == {
        FIRST: ActionStatus.COMPLETED.value,
        READER: ActionStatus.COMPLETED.value,
    }, transcript
    if run_mode == "online":
        # The file's warning must not say its readers get nothing: the other file feeds them.
        assert "None of them reaches downstream actions" in transcript
        assert "Downstream actions will receive no input" not in transcript


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_its_reader_holds_nothing_for_the_file_the_guard_filtered_in_either_run_mode(
    tmp_path, run_mode
):
    """The reader's input for that file is empty. Batch sent nothing for it and kept
    the rows it had built from the records the guard now filters."""
    root = _model_project_whose_guard_now_filters_one_whole_file(tmp_path, run_mode)

    transcript = _run_to_the_end(root)

    assert _rows_by_file(root, READER, _model_backend) == {
        "other.json": 2,
        "pages.json": 0,
    }, transcript
    assert _statuses(root)[READER] == ActionStatus.COMPLETED.value
