"""A record an action sends elsewhere leaves that branch, and is not dead below it.

An action marked ``_sends_elsewhere`` records a record its guard filters as
``filtered`` with reason ``sent_elsewhere``. Below it the record is gone from that
branch, as a filtered record is, but an action marked ``_gathers`` takes it back from
the branch it went to. An action whose every record went elsewhere completes on no
records instead of being skipped, and its readers run on nothing. Nothing reports such
a record as filtered. Every claim holds in both run modes: the two LLM actions run
against the provider mock under ``run_mode: online`` and ``run_mode: batch``.
"""

from __future__ import annotations

import json
import re

import pytest

from agent_actions.record.reasons import SENT_ELSEWHERE
from agent_actions.storage.backend import DISPOSITION_FILTERED
from tests._support.agac_cli import run_agac
from tests.integration.test_a_reader_with_a_batch_out_follows_an_upstream_edit import (
    _config,
    _rows,
    _run_to_the_end,
    _statuses,
)
from tests.integration.test_retry_selection_under_batch import WORKFLOW, _agac, _backend, _project

RUN_MODES = pytest.mark.parametrize("run_mode", ["online", "batch"])
PAGES = 4

SCHEMA = """name: branch_summary
fields:
  - id: summary
    type: string
additionalProperties: true
"""


def _action(name, *, guard=None, dependencies=(), observe=("source.page_content",), extra=()):
    lines = [
        f"  - name: {name}",
        '    intent: "Summarise"',
        "    schema: branch_summary",
        "    prompt: $p.Summarize",
        f"    context_scope: {{ observe: [{', '.join(observe)}] }}",
    ]
    if dependencies:
        lines.append(f"    dependencies: [{', '.join(dependencies)}]")
    if guard:
        lines.append(f"    guard: {{ condition: '{guard}', on_false: \"filter\" }}")
    lines.extend(f"    {line}" for line in extra)
    return "\n".join(lines) + "\n"


SENDS = ("_sends_elsewhere: true",)
GATHERS = ("_gathers: true",)
NONE = 'source.page_content == "none"'
ANY = 'source.page_content != "none"'
FIRST_PAGE = 'source.page_content == "page 0"'
OTHER_PAGES = 'source.page_content != "page 0"'
GATE = ("source.page_content", "gate.summary")


def _gatherer(*branches):
    return _action(
        "joined",
        dependencies=branches,
        observe=("source.page_content", *(f"{b}.*" for b in branches)),
        extra=GATHERS,
    )


def _make(tmp_path, run_mode, *actions):
    root = _project(tmp_path)
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(PAGES)])
    )
    (root / "schema" / WORKFLOW / "branch_summary.yml").write_text(SCHEMA)
    config = _config(root)
    head = config.read_text().split("\nactions:")[0]
    head = head.replace("run_mode: batch", f"run_mode: {run_mode}")
    config.write_text(head + "\nactions:\n" + "".join(actions))
    return root


def _count(project, action):
    return len(_rows(project, action))


def _dispositions(project, action):
    backend = _backend(project)
    try:
        return [
            (row["disposition"], row.get("reason"))
            for row in backend.get_disposition(action, snapshots=False)
        ]
    finally:
        backend.close()


SPLIT = (
    _action("left", guard=FIRST_PAGE, extra=SENDS),
    _action("right", guard=OTHER_PAGES, extra=SENDS),
    _gatherer("left", "right"),
)


@pytest.fixture
def split(tmp_path, request):
    root = _make(tmp_path, request.param, *SPLIT)
    transcript = _run_to_the_end(root, "--fresh")
    return root, transcript


SPLIT_MODES = pytest.mark.parametrize("split", ["online", "batch"], indirect=True)


@RUN_MODES
def test_an_action_whose_every_record_went_elsewhere_completes_and_its_reader_runs_on_none(
    tmp_path, run_mode
):
    root = _make(
        tmp_path,
        run_mode,
        _action("left", guard=NONE, extra=SENDS),
        _action("reader", dependencies=("left",), observe=("left.summary",)),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert _statuses(root) == {"left": "completed", "reader": "completed"}, transcript
    assert (_count(root, "left"), _count(root, "reader")) == (0, 0)
    assert "skipped —" not in transcript


EMPTY_BRANCH = (
    _action("left", guard=NONE, extra=SENDS),
    _action("right", guard=ANY, extra=SENDS),
    _gatherer("left", "right"),
)


@RUN_MODES
def test_a_gatherer_after_an_empty_branch_holds_every_record_of_the_other(tmp_path, run_mode):
    root = _make(tmp_path, run_mode, *EMPTY_BRANCH)

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, a) for a in ("left", "right", "joined")] == [0, PAGES, PAGES]


@SPLIT_MODES
def test_records_split_between_two_branches_meet_again_at_the_gatherer(split):
    root, transcript = split

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, a) for a in ("left", "right", "joined")] == [1, PAGES - 1, PAGES]


@SPLIT_MODES
def test_a_record_sent_elsewhere_is_recorded_filtered_for_that_reason(split):
    root, _ = split

    assert _dispositions(root, "left").count((DISPOSITION_FILTERED, SENT_ELSEWHERE)) == PAGES - 1
    assert _dispositions(root, "right").count((DISPOSITION_FILTERED, SENT_ELSEWHERE)) == 1


@RUN_MODES
def test_a_record_sent_elsewhere_does_not_come_back_through_another_input_of_its_branch(
    tmp_path, run_mode
):
    """The branch's second action also reads the action above the split: the records
    the branch sent elsewhere reach it there, and must not run in this branch."""
    root = _make(
        tmp_path,
        run_mode,
        _action("first"),
        _action(
            "left",
            guard=FIRST_PAGE,
            dependencies=("first",),
            observe=("source.page_content", "first.summary"),
            extra=SENDS,
        ),
        _action(
            "left_next",
            dependencies=("left", "first"),
            observe=("source.page_content", "left.*", "first.summary"),
        ),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, a) for a in ("first", "left", "left_next")] == [PAGES, 1, 1]


@RUN_MODES
def test_a_record_an_ordinary_guard_filtered_above_stays_dead_at_the_gatherer(tmp_path, run_mode):
    root = _make(
        tmp_path,
        run_mode,
        _action("gate", guard='source.page_content != "page 3"'),
        _action("left", guard=FIRST_PAGE, dependencies=("gate",), observe=GATE, extra=SENDS),
        _action("right", guard=OTHER_PAGES, dependencies=("gate",), observe=GATE, extra=SENDS),
        _gatherer("left", "right"),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert _count(root, "joined") == PAGES - 1


@SPLIT_MODES
def test_the_run_reports_no_record_sent_elsewhere_as_filtered(split):
    _, transcript = split
    flat = " ".join(transcript.split())

    assert not re.search(r"[1-9]\d* filtered", flat), flat
    assert "records filtered by guard" not in flat
    assert "✓ left 1 record " in flat, flat
    if "(batch)" not in flat:
        # Online, the pre-filter reports what the guard sent elsewhere.
        assert "Guard pre-filter for 'left': 1 passed" in flat, flat
        assert "3 sent elsewhere" in flat, flat


def _table_row(output, action):
    for line in output.splitlines():
        cells = [c.strip() for c in re.split(r"[│|┃]", line)]
        if action in cells:
            return cells[cells.index(action) :]
    raise AssertionError(f"no row for {action} in\n{output}")


@SPLIT_MODES
def test_agac_dispositions_counts_a_record_sent_elsewhere_apart_from_filtered(split):
    root, _ = split

    code, output = _agac(root, "dispositions", "-a", WORKFLOW)

    assert code == 0, output
    header = _table_row(output, "Action")
    left = dict(zip(header, _table_row(output, "left"), strict=False))
    assert left["Filtered"] == "0", output
    assert left["Sent elsewhere"] == str(PAGES - 1), output
    assert left["Total"] == "1", output


@SPLIT_MODES
def test_agac_dispositions_json_counts_a_record_sent_elsewhere_as_the_table_does(split):
    root, _ = split

    result = run_agac(root, "dispositions", "-w", WORKFLOW, "--json")

    assert result.returncode == 0, result.stderr
    report = {entry["name"]: entry for entry in json.loads(result.stdout)["actions"]}
    assert report["left"]["sent_elsewhere"] == PAGES - 1
    assert report["left"]["counts"]["filtered"] == 0
    assert report["left"]["total"] == 1
    assert report["joined"]["sent_elsewhere"] == 0


@RUN_MODES
def test_a_second_run_finds_every_action_complete_the_empty_branch_too(tmp_path, run_mode):
    root = _make(tmp_path, run_mode, *EMPTY_BRANCH)
    _run_to_the_end(root, "--fresh")

    code, output = _agac(root, "run", "-a", WORKFLOW)

    assert code == 0, output
    flat = " ".join(output.split())
    assert "— 3 completed" in flat, flat
    assert "Guard pre-filter" not in flat and " records in " not in flat, flat
    assert _statuses(root) == {"left": "completed", "right": "completed", "joined": "completed"}


@SPLIT_MODES
def test_retry_selects_no_record_sent_elsewhere(split):
    root, _ = split
    before = {a: _dispositions(root, a) for a in ("left", "right")}

    code, output = _agac(root, "retry", "-a", WORKFLOW)

    assert code == 0, output
    assert "Nothing to retry" in " ".join(output.split()), output
    assert {a: _dispositions(root, a) for a in ("left", "right")} == before


PAGE_1 = 'source.page_content == "page 1"'
FIRST_TWO = 'source.page_content == "page 0" or source.page_content == "page 1"'
LAST_TWO = 'source.page_content == "page 2" or source.page_content == "page 3"'
FIRST = ("source.page_content", "first.summary")


def _summaries(project, action):
    return sorted(row["source_guid"] for row in _rows(project, action))


@RUN_MODES
def test_a_record_no_branch_took_stays_dead_at_the_gatherer(tmp_path, run_mode):
    """Pages 2 and 3 pass neither guard. The gatherer also reads the action above the
    split, and they must not come back through it."""
    root = _make(
        tmp_path,
        run_mode,
        _action("first"),
        _action("left", guard=FIRST_PAGE, dependencies=("first",), observe=FIRST, extra=SENDS),
        _action("right", guard=PAGE_1, dependencies=("first",), observe=FIRST, extra=SENDS),
        _action(
            "joined",
            dependencies=("left", "right", "first"),
            observe=("source.page_content", "left.*", "right.*", "first.summary"),
            extra=GATHERS,
        ),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, a) for a in ("first", "left", "right", "joined")] == [PAGES, 1, 1, 2]


@RUN_MODES
def test_a_record_of_another_branch_does_not_enter_this_one_at_an_inner_gatherer(
    tmp_path, run_mode
):
    """Outer branch A takes pages 0 and 1, B pages 2 and 3; inside A, A1 takes page 0 and
    A2 page 1. A's inner gatherer also reads the action above the outer split."""
    root = _make(
        tmp_path,
        run_mode,
        _action("first"),
        _action("a", guard=FIRST_TWO, dependencies=("first",), observe=FIRST, extra=SENDS),
        _action("b", guard=LAST_TWO, dependencies=("first",), observe=FIRST, extra=SENDS),
        _action(
            "a1",
            guard=FIRST_PAGE,
            dependencies=("a",),
            observe=("source.page_content", "a.summary"),
            extra=SENDS,
        ),
        _action(
            "a2",
            guard=PAGE_1,
            dependencies=("a",),
            observe=("source.page_content", "a.summary"),
            extra=SENDS,
        ),
        _action(
            "inner",
            dependencies=("a1", "a2", "first"),
            observe=("source.page_content", "a1.*", "a2.*", "first.summary"),
            extra=GATHERS,
        ),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, x) for x in ("a", "b", "a1", "a2", "inner")] == [2, 2, 1, 1, 2]


@RUN_MODES
def test_an_action_below_the_gatherer_that_also_reads_above_the_split_keeps_every_record(
    tmp_path, run_mode
):
    root = _make(
        tmp_path,
        run_mode,
        _action("first"),
        _action("left", guard=FIRST_PAGE, dependencies=("first",), observe=FIRST, extra=SENDS),
        _action("right", guard=OTHER_PAGES, dependencies=("first",), observe=FIRST, extra=SENDS),
        _gatherer("left", "right"),
        _action(
            "after",
            dependencies=("joined", "first"),
            observe=("source.page_content", "joined.summary", "first.summary"),
        ),
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert [_count(root, a) for a in ("joined", "after")] == [PAGES, PAGES]


@RUN_MODES
def test_marking_a_split_and_its_gatherer_is_an_edit_of_each(tmp_path, run_mode):
    """The keys change which records a reader gets, so adding them is an edit: the run
    names it, and a rerun of the split gives the gatherer every record."""
    plain = (
        _action("left", guard=FIRST_PAGE),
        _action("right", guard=OTHER_PAGES),
        _action(
            "joined",
            dependencies=("left", "right"),
            observe=("source.page_content", "left.*", "right.*"),
        ),
    )
    root = _make(tmp_path, run_mode, *plain)
    _run_to_the_end(root, "--fresh")
    assert _count(root, "joined") == 0

    config = _config(root)
    head = config.read_text().split("\nactions:")[0]
    config.write_text(head + "\nactions:\n" + "".join(SPLIT))
    transcript = " ".join(_run_to_the_end(root).split())

    for action in ("left", "right", "joined"):
        assert f"--rerun {action}" in transcript, transcript
    transcript = _run_to_the_end(root, "--rerun", "left", "--rerun", "right")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert _count(root, "joined") == PAGES, transcript
    assert _dispositions(root, "left").count((DISPOSITION_FILTERED, SENT_ELSEWHERE)) == PAGES - 1
