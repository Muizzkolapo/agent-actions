"""A batch action holds no row for a record its guard filters, as online holds none.

`summarize` and `publish` both run under `run_mode: batch` against the provider mock,
each to completion, before `summarize` is given a guard. Editing it resets both, so
every record reaches the guard again. Where the guard filters every record the action
holds nothing and is skipped, and its reader is skipped and emptied, as online
(test_skipped_reader_drops_stale_rows). Where it filters one, that record's row goes.
"""

import json

import pytest

from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    ANCHOR,
    FIRST,
    READER,
    READER_ACTION,
    _config,
    _guids,
    _rows,
    _run,
    _run_to_the_end,
    _statuses,
)
from tests.integration.test_retry_selection_under_batch import (
    RECORDS,
    WORKFLOW,
    _backend,
    _project,
)

FILTER_ALL = '    guard: { condition: \'source.page_content == "none"\', on_false: "filter" }\n'
FILTER_PAGE_0 = (
    '    guard: { condition: \'source.page_content != "page 0"\', on_false: "filter" }\n'
)
MODES = pytest.mark.parametrize("mode", ["sequential", "parallel"])


def _add_guard(project, guard):
    config = _config(project)
    assert ANCHOR in config.read_text()
    config.write_text(config.read_text().replace(ANCHOR, ANCHOR + guard, 1))


def _node_reason(project, action):
    backend = _backend(project)
    try:
        rows = backend.get_disposition(action, record_id=NODE_LEVEL_RECORD_ID)
        return rows[0].get("reason") if rows else None
    finally:
        backend.close()


@pytest.fixture
def both_collected(tmp_path):
    root = _project(tmp_path)
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(RECORDS)])
    )
    config = _config(root)
    config.write_text(config.read_text().rstrip("\n") + "\n" + READER_ACTION)

    assert "run again" in _run(root, "--fresh"), "the fixture did not pause on submission"
    _run_to_the_end(root)

    assert _statuses(root) == {
        FIRST: ActionStatus.COMPLETED.value,
        READER: ActionStatus.COMPLETED.value,
    }
    assert len(_guids(root, FIRST)) == len(_guids(root, READER)) == RECORDS
    return root


@MODES
def test_an_action_whose_guard_filters_everything_holds_nothing_and_its_reader_is_skipped(
    both_collected, mode
):
    project = both_collected
    _add_guard(project, FILTER_ALL)

    transcript = _run_to_the_end(project, "-e", mode)

    assert _rows(project, FIRST) == []
    assert _rows(project, READER) == []
    assert _statuses(project) == {
        FIRST: ActionStatus.SKIPPED.value,
        READER: ActionStatus.SKIPPED.value,
    }, transcript
    # The path, not just the outcome: the reader was skipped, not run on nothing.
    assert _node_reason(project, READER) == f"Upstream dependency '{FIRST}' skipped"
    assert "submitted:" not in transcript, transcript


def test_a_record_the_guard_filters_leaves_no_row_in_the_action_or_its_reader(both_collected):
    project = both_collected
    (filtered,) = [r["source_guid"] for r in _rows(project, FIRST) if '"page 0"' in json.dumps(r)]
    kept = sorted(set(_guids(project, FIRST)) - {filtered})
    _add_guard(project, FILTER_PAGE_0)

    transcript = _run_to_the_end(project)

    assert _guids(project, FIRST) == kept, transcript
    assert _guids(project, READER) == kept, transcript


def test_a_second_run_keeps_it_empty_and_lifting_the_filter_restores_it(both_collected):
    project = both_collected
    _add_guard(project, FILTER_ALL)
    _run_to_the_end(project)
    _run_to_the_end(project)
    assert _rows(project, READER) == []

    config = _config(project)
    config.write_text(config.read_text().replace(FILTER_ALL, ""))
    _run_to_the_end(project)

    assert len(_guids(project, FIRST)) == len(_guids(project, READER)) == RECORDS
    assert _statuses(project) == {
        FIRST: ActionStatus.COMPLETED.value,
        READER: ActionStatus.COMPLETED.value,
    }
