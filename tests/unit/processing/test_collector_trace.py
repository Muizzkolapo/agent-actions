"""Everything one collection does, for a batch that reaches every status branch.

Pins the output rows and their states, the disposition rows in write order, the
events, the log lines, the stats and what lands on the context, so a change to how
the collector is put together cannot change what it does.
"""

import logging
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.record.reasons import GUARD_SKIP, SENT_ELSEWHERE
from agent_actions.record.state import RecordState

ACTION = "act"


def _row(guid: str | None, **content: object) -> dict:
    row: dict = {"target_id": f"t-{guid}", "content": {ACTION: dict(content)}}
    if guid is not None:
        row["source_guid"] = guid
    return row


def _failing(guid: str | None) -> dict:
    return _row(guid, expect={"overall_pass": False})


def _results() -> list[ProcessingResult]:
    carried_answer = _row("cf-1")
    carried_answer["_state"] = RecordState.PROCESSED.value
    carried_failure = _row("cf-2")
    carried_failure["_state"] = RecordState.FAILED.value
    bundled_skip = _row("sk-2")
    filtered_bundle = ProcessingResult.filtered()
    filtered_bundle.data = [_row("fl-3")]
    return [
        ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[carried_answer],
            source_guid="cf-1",
            skip_reason=CARRY_FORWARD_REASON,
        ),
        ProcessingResult(
            status=ProcessingStatus.SUCCESS, data=[], skip_reason=CARRY_FORWARD_REASON
        ),
        ProcessingResult.success([_row("pe-1", _parse_error="bad json")], source_guid="pe-1"),
        ProcessingResult.success(
            [_row("pe-2", _parse_error="bad"), _row("ok-2"), _failing("ck-2"), _failing(None)]
        ),
        ProcessingResult.success([_row(None, _parse_error="bad")]),
        ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[_failing("ok-1")],
            source_guid="ok-1",
            collapse_contributor_guids=["in-a", "in-b"],
        ),
        ProcessingResult.success([_row("ok-1")], source_guid="ok-1"),
        ProcessingResult.skipped(None, GUARD_SKIP, source_guid="sk-1"),
        ProcessingResult.skipped([bundled_skip], "custom_skip"),
        ProcessingResult.exhausted(
            "rate limited",
            data=[_row("ex-1")],
            source_guid="ex-1",
            source_snapshot={"q": 1},
        ),
        ProcessingResult.exhausted("", data=[_row("ex-2")], input_record={"q": 2}),
        ProcessingResult.failed("timeout", source_guid="fa-1", input_record={"q": 3}),
        ProcessingResult(status=ProcessingStatus.FAILED, data=[_row("fa-2")], error="bad item"),
        ProcessingResult.failed("lost"),
        ProcessingResult(
            status=ProcessingStatus.FILTERED, source_guid="fl-1", skip_reason=SENT_ELSEWHERE
        ),
        ProcessingResult.filtered(source_guid="fl-2"),
        filtered_bundle,
        ProcessingResult.filtered(),
        ProcessingResult(
            status=ProcessingStatus.UNPROCESSED, data=[], skip_reason=CARRY_FORWARD_REASON
        ),
        ProcessingResult.unprocessed([], "upstream_failed", source_guid="un-1"),
        ProcessingResult.unprocessed([_row("un-2")], GUARD_SKIP),
        ProcessingResult.unprocessed([_row("un-3")], "upstream_failed", source_guid="un-3"),
        ProcessingResult.unprocessed([carried_failure], CARRY_FORWARD_REASON, source_guid="cf-2"),
        ProcessingResult.deferred("task-9", source_guid="de-1"),
        ProcessingResult.deferred("task-10"),
    ]


def _trace(context: ProcessingContext | None, refuse: bool, caplog) -> dict:
    backend = MagicMock()
    if refuse:
        backend.set_dispositions_batch.side_effect = RuntimeError("disk full")
    events: list = []
    caplog.set_level(logging.DEBUG, logger="agent_actions.processing.result_collector")
    with patch(
        "agent_actions.processing.result_collector.fire_event",
        side_effect=lambda e: events.append((e.code, e.data)),
    ):
        output, stats = collect_results_from_processing_results(
            _results(),
            ACTION,
            storage_backend=backend,
            agent_config={"guard": {"clause": "x > 1", "behavior": "filter"}},
            context=context,
        )
    return {
        "output": [(r.get("source_guid"), r.get("_state")) for r in output],
        "batch": [c.args[0] for c in backend.set_dispositions_batch.call_args_list],
        "credited": [c.args for c in backend.credit_rows_collected.call_args_list],
        "events": events,
        "logs": [
            (r.levelname, r.getMessage())
            for r in caplog.records
            if r.name == "agent_actions.processing.result_collector"
        ],
        "stats": asdict(stats),
    }


_BATCH_ROWS = [
    ("act", "pe-1", "failed", "parse_error", None, None, None),
    ("act", "pe-2", "failed", "parse_error", None, None, None),
    ("act", "ok-2", "success", None, None, None, None),
    ("act", "ck-2", "success", "expectations_failed", None, None, None),
    ("act", "ok-1", "success", "expectations_failed", None, None, None),
    ("act", "in-a", "success", "consumed_into_output", None, None, None),
    ("act", "in-b", "success", "consumed_into_output", None, None, None),
    ("act", "ok-1", "success", "expectations_failed", None, None, None),
    ("act", "sk-1", "passthrough", "guard_skip", None, None, None),
    ("act", "sk-2", "passthrough", "custom_skip", None, None, None),
    (
        "act",
        "ex-1",
        "exhausted",
        "exhausted_after_unknown_attempts",
        None,
        '{"q": 1}',
        "rate limited",
    ),
    ("act", "ex-2", "exhausted", "exhausted_after_unknown_attempts", None, '{"q": 2}', ""),
    ("act", "fa-1", "failed", "timeout", None, '{"q": 3}', "timeout"),
    ("act", "fa-2", "failed", "bad item", None, None, "bad item"),
    ("act", "fl-1", "filtered", "sent_elsewhere", None, None, None),
    ("act", "fl-2", "filtered", "guard_filter", None, None, None),
    ("act", "fl-3", "filtered", "guard_filter", None, None, None),
    ("act", "un-1", "unprocessed", "upstream_failed", None, None, None),
    ("act", "un-2", "unprocessed", "guard_skip", None, None, None),
    ("act", "un-3", "unprocessed", "upstream_failed", None, None, None),
    ("act", "de-1", "deferred", "batch_queued:task_id=task-9", None, None, None),
]

_OUTPUT = [
    ("cf-1", "processed"),
    ("pe-1", "failed"),
    ("pe-2", "failed"),
    ("ok-2", "processed"),
    ("ck-2", "processed"),
    (None, "processed"),
    (None, "failed"),
    ("ok-1", "processed"),
    ("ok-1", "processed"),
    ("sk-2", "guard_skipped"),
    ("ex-1", "exhausted"),
    ("ex-2", "exhausted"),
    ("fa-1", "failed"),
    ("fa-2", "failed"),
    (None, "failed"),
    ("un-2", "guard_skipped"),
    ("un-3", "cascade_skipped"),
    ("cf-2", "failed"),
]

_STATS = {
    "success": 3,
    "failed": 6,
    "skipped": 2,
    "filtered": 3,
    "exhausted": 2,
    "deferred": 2,
    "unprocessed": 3,
    "carry_forward": 4,
    "carried_success": 1,
    "causes": ("rate limited", "", "timeout", "bad item", "lost"),
    "guard_skipped": 1,
    "checks_failed": 3,
    "sent_elsewhere": 1,
    "cases": None,
}


def _collected(index: int, status: str) -> tuple:
    return ("RC002", {"action_name": ACTION, "result_index": index, "status": status})


def _exhausted(index: int, guid: str) -> tuple:
    return (
        "RC004",
        {
            "action_name": ACTION,
            "record_index": index,
            "source_guid": guid,
            "reason": "exhausted_after_unknown_attempts",
        },
    )


_EVENTS = [
    ("RC001", {"action_name": ACTION, "total_results": 25}),
    _collected(2, "failed"),
    _collected(3, "failed"),
    _collected(3, "success"),
    _collected(4, "failed"),
    _collected(5, "success"),
    _collected(6, "success"),
    _collected(7, "skipped"),
    _collected(8, "skipped"),
    _exhausted(9, "ex-1"),
    _exhausted(10, ""),
    _collected(11, "failed"),
    _collected(12, "failed"),
    _collected(13, "failed"),
    _collected(14, "filtered"),
    _collected(15, "filtered"),
    _collected(16, "filtered"),
    _collected(17, "filtered"),
    _collected(19, "unprocessed"),
    _collected(20, "unprocessed"),
    _collected(21, "unprocessed"),
    _collected(23, "deferred"),
    _collected(24, "deferred"),
]

_LOGS = [
    ("INFO", "[act] 2 records exhausted retries (on_exhausted=return_last)"),
    (
        "WARNING",
        "[act] SUCCESS result source_guid=pe-1 contains _parse_error in 1 row(s) "
        "— dispositioned as FAILED",
    ),
    (
        "WARNING",
        "[act] SUCCESS result source_guid=None contains _parse_error in 1 row(s) "
        "— dispositioned as FAILED",
    ),
    ("DEBUG", "Collected SUCCESS result source_guid=None count=3"),
    (
        "WARNING",
        "[act] SUCCESS result source_guid=None contains _parse_error in 1 row(s) "
        "— dispositioned as FAILED",
    ),
    (
        "WARNING",
        "[act] 1 data item(s) but none carry source_guid — "
        "dispositions not written (risk of reprocessing on next run)",
    ),
    ("DEBUG", "Collected SUCCESS result source_guid=ok-1 count=1"),
    ("DEBUG", "Collected SUCCESS result source_guid=ok-1 count=1"),
    ("DEBUG", "Collected SKIPPED result source_guid=sk-1 count=0"),
    ("DEBUG", "Collected SKIPPED result source_guid=None count=1"),
    ("DEBUG", "Collected EXHAUSTED result source_guid=ex-1 attempts=unknown"),
    ("DEBUG", "Collected EXHAUSTED result source_guid=None attempts=unknown"),
    ("ERROR", "[act] timeout (record fa)"),
    ("ERROR", "[act] bad item (record unknown)"),
    ("ERROR", "[act] lost (record unknown)"),
    (
        "WARNING",
        "[act] FAILED result has no source_guid and no data — "
        "disposition not written (risk of reprocessing on next run)",
    ),
    ("DEBUG", "Collected FILTERED result source_guid=fl-1"),
    ("DEBUG", "Collected FILTERED result source_guid=fl-2"),
    ("DEBUG", "Collected FILTERED result source_guid=None"),
    ("DEBUG", "Collected FILTERED result source_guid=None"),
    (
        "WARNING",
        "[act] FILTERED result has no source_guid and no data — "
        "disposition not written (risk of reprocessing on next run)",
    ),
    ("DEBUG", "Collected UNPROCESSED result source_guid=un-1 count=0"),
    ("DEBUG", "Collected UNPROCESSED result source_guid=None count=1"),
    ("DEBUG", "Collected UNPROCESSED result source_guid=un-3 count=1"),
    ("INFO", "Collected DEFERRED result source_guid=de-1 task_id=task-9"),
    ("INFO", "Collected DEFERRED result source_guid=None task_id=task-10"),
    (
        "WARNING",
        "[act] DEFERRED result has no source_guid — "
        "disposition not written (risk of reprocessing on next run)",
    ),
    ("INFO", "[act] 7/25 records are tombstones (skipped=2, exhausted=2, unprocessed=3)"),
]


def _complete(target: str) -> tuple:
    return (
        "RC003",
        {
            "action_name": ACTION,
            "total_success": 3,
            "total_skipped": 2,
            "total_filtered": 3,
            "total_failed": 6,
            "total_exhausted": 2,
            "total_unprocessed": 3,
            "total_guard_skipped": 1,
            "total_deferred": 2,
            "total_sent_elsewhere": 1,
            "guard_condition": "x > 1",
            "guard_on_false": "filter",
            "target_relative_path": target,
        },
    )


def test_a_collection_without_a_context(caplog):
    trace = _trace(None, refuse=False, caplog=caplog)

    assert trace["output"] == _OUTPUT
    assert trace["batch"] == [_BATCH_ROWS]
    assert trace["credited"] == [(ACTION, 16)]
    assert trace["events"] == [*_EVENTS, _complete("")]
    assert trace["logs"] == _LOGS
    assert trace["stats"] == _STATS


def test_a_context_that_defers_kept_rows_and_a_store_that_refuses(caplog):
    context = ProcessingContext(
        agent_config={},
        agent_name=ACTION,
        target_relative_path="out/file.json",
        defer_kept_dispositions=True,
    )

    trace = _trace(context, refuse=True, caplog=caplog)

    kept = [row for row in _BATCH_ROWS if row[2] in ("success", "passthrough")]
    written = [row for row in _BATCH_ROWS if row not in kept]
    assert trace["batch"] == [written]
    assert context.kept_dispositions == kept
    assert context.dispositions_not_stored == {row[1] for row in written}
    assert context.failure_not_stored is not None
    assert context.failure_not_stored.context["record_ids"] == [
        "ex-1",
        "ex-2",
        "fa-1",
        "fa-2",
        "pe-1",
        "pe-2",
    ]
    assert trace["output"] == _OUTPUT
    assert trace["events"] == [*_EVENTS, _complete("out/file.json")]
    assert trace["logs"][: len(_LOGS) - 1] == _LOGS[:-1]
    assert trace["logs"][-2:] == [
        ("ERROR", f"Failed to batch-write {len(written)} dispositions for act"),
        _LOGS[-1],
    ]
    assert trace["stats"] == _STATS


@pytest.mark.parametrize("guid", ["fl-x", None])
def test_every_result_filtered_warns_that_nothing_reaches_downstream(guid, caplog):
    caplog.set_level(logging.WARNING, logger="agent_actions.processing.result_collector")
    result = ProcessingResult.filtered(source_guid=guid)
    result.data = [_row("fl-x")]

    output, stats = collect_results_from_processing_results(
        [result], ACTION, agent_config={"guard": "not-a-dict"}
    )

    assert output == []
    assert stats.filtered == 1
    assert (
        "[act] All 1 records filtered by guard (unknown condition). "
        "None of them reaches downstream actions."
    ) in [r.getMessage() for r in caplog.records]
