"""A record shipped with a failing verdict is a success that says so.

`on_exhausted: return_last` and `repair: none` ship the record with `overall_pass: false`
by design, so a guard below can filter on it. The collector keeps it a success and gives
the disposition the reason `expectations_failed`, and credits the count for the run line.
"""

import pytest

from agent_actions.processing.result_collector import (
    collect_results_from_processing_results,
    failed_its_checks,
)
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.reasons import EXPECTATIONS_FAILED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


class _Backend(SQLiteBackend):
    """A real store that also keeps the disposition rows it was handed."""

    def set_dispositions_batch(self, rows) -> None:
        self.handed = list(rows)
        super().set_dispositions_batch(rows)


@pytest.fixture
def backend(tmp_path):
    store = _Backend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    store.handed = []
    yield store
    store.close()


def _verdict(overall_pass: bool, *, warn_failed: bool = False) -> dict:
    outcomes = [
        {"id": "rule", "type": "matches_regex", "severity": "error", "passed": overall_pass},
    ]
    if warn_failed:
        outcomes.append(
            {"id": "soft", "type": "matches_regex", "severity": "warn", "passed": False}
        )
    return {
        "overall_pass": overall_pass,
        "failed": [] if overall_pass else ["rule"],
        "outcomes": outcomes,
    }


def _row(guid: str, verdict: dict | None) -> dict:
    own = {"summary": "s"}
    if verdict is not None:
        own["expect"] = verdict
    return {"source_guid": guid, "content": {"a": own}}


def _reasons(backend) -> dict[str, tuple[str, str | None]]:
    return {row[1]: (row[2], row[3]) for row in backend.handed}


def test_a_failing_verdict_is_success_with_its_reason(backend):
    result = ProcessingResult.success(data=[_row("g1", _verdict(False))], source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", EXPECTATIONS_FAILED)}
    assert stats.checks_failed == 1


def test_a_passing_verdict_keeps_no_reason(backend):
    result = ProcessingResult.success(data=[_row("g1", _verdict(True))], source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", None)}
    assert stats.checks_failed == 0


def test_a_warn_only_failure_is_not_counted(backend):
    verdict = _verdict(True, warn_failed=True)
    result = ProcessingResult.success(data=[_row("g1", verdict)], source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", None)}
    assert stats.checks_failed == 0


def test_bundled_file_rows_are_marked_one_by_one(backend):
    result = ProcessingResult.success(
        data=[_row("g1", _verdict(False)), _row("g2", _verdict(True))], source_guid=None
    )

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {
        "g1": ("success", EXPECTATIONS_FAILED),
        "g2": ("success", None),
    }
    assert stats.checks_failed == 1


def test_a_row_without_a_verdict_is_untouched(backend):
    result = ProcessingResult.success(data=[_row("g1", None)], source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", None)}
    assert stats.checks_failed == 0


def test_a_record_that_expands_counts_once(backend):
    rows = [_row("g1", _verdict(False)), _row("g1", _verdict(False))]
    result = ProcessingResult.success(data=rows, source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert stats.checks_failed == 1


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param(_row("g", _verdict(False)), True, id="own-verdict-fails"),
        pytest.param(_row("g", _verdict(True)), False, id="own-verdict-passes"),
        pytest.param(
            {"source_guid": "g", "content": {"upstream": {"expect": _verdict(False)}}},
            False,
            id="another-actions-verdict",
        ),
        pytest.param({"source_guid": "g", "content": "text"}, False, id="content-not-a-dict"),
        pytest.param({"source_guid": "g"}, False, id="no-content"),
    ],
)
def test_only_the_actions_own_failing_verdict_counts(row, expected):
    assert failed_its_checks(row, "a") is expected


def test_an_empty_source_guid_costs_the_other_records_nothing(backend):
    results = [
        ProcessingResult.success(data=[_row("", _verdict(False))], source_guid=""),
        ProcessingResult.success(data=[_row("g2", _verdict(False))], source_guid="g2"),
    ]

    _, stats = collect_results_from_processing_results(results, "a", storage_backend=backend)

    assert _reasons(backend) == {"g2": ("success", EXPECTATIONS_FAILED)}
    stored = [
        tuple(row)
        for row in backend.connection.execute(
            "select record_id, reason from record_disposition where action_name = 'a'"
        )
    ]
    assert stored == [("g2", EXPECTATIONS_FAILED)]


def test_a_bundled_record_with_mixed_rows_is_one_failed_record(backend):
    rows = [
        _row("g1", _verdict(True)),
        _row("g1", _verdict(False)),
        _row("g1", _verdict(False)),
        _row("g2", _verdict(True)),
    ]
    result = ProcessingResult.success(data=rows, source_guid=None)

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {
        "g1": ("success", EXPECTATIONS_FAILED),
        "g2": ("success", None),
    }
    assert stats.checks_failed == 1


def test_a_bundled_failing_row_without_a_guid_is_still_counted(backend):
    rows = [_row("g1", _verdict(False)), {"content": {"a": {"expect": _verdict(False)}}}]
    result = ProcessingResult.success(data=rows, source_guid=None)

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", EXPECTATIONS_FAILED)}
    assert stats.checks_failed == 2


def test_one_failing_row_of_an_expanded_record_marks_the_record(backend):
    rows = [_row("g1", _verdict(True)), _row("g1", _verdict(False))]
    result = ProcessingResult.success(data=rows, source_guid="g1")

    _, stats = collect_results_from_processing_results([result], "a", storage_backend=backend)

    assert _reasons(backend) == {"g1": ("success", EXPECTATIONS_FAILED)}
    assert stats.checks_failed == 1


def _carried_as_file_mode(row):
    from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON

    carried = ProcessingResult.unprocessed([row], CARRY_FORWARD_REASON, source_guid="old")
    carried.skip_reason = CARRY_FORWARD_REASON
    return carried


def _carried_as_record_mode(row):
    from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
    from agent_actions.processing.types import ProcessingStatus

    return ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[row],
        source_guid="old",
        skip_reason=CARRY_FORWARD_REASON,
    )


@pytest.mark.parametrize("carry", [_carried_as_file_mode, _carried_as_record_mode])
def test_a_carried_record_with_a_failing_verdict_is_not_counted_again(backend, carry):
    carried = carry(_row("old", _verdict(False)))
    new = ProcessingResult.success(data=[_row("new", _verdict(False))], source_guid="new")

    _, stats = collect_results_from_processing_results([carried, new], "a", storage_backend=backend)

    assert stats.checks_failed == 1
    assert "old" not in _reasons(backend)


def test_a_record_resumed_as_one_result_per_row_is_one_failed_record(backend):
    # A resumed expansion: each checkpointed row comes back as its own keyed result.
    results = [
        ProcessingResult.success(data=[_row("g1", _verdict(True))], source_guid="g1"),
        ProcessingResult.success(data=[_row("g1", _verdict(False))], source_guid="g1"),
        ProcessingResult.success(data=[_row("g1", _verdict(False))], source_guid="g1"),
    ]

    _, stats = collect_results_from_processing_results(results, "a", storage_backend=backend)

    assert {row[3] for row in backend.handed if row[1] == "g1"} == {EXPECTATIONS_FAILED}
    stored = [
        tuple(row)
        for row in backend.connection.execute(
            "select record_id, reason from record_disposition where action_name = 'a'"
        )
    ]
    assert stored == [("g1", EXPECTATIONS_FAILED)]
    assert stats.checks_failed == 1
