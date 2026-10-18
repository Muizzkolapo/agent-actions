"""The dispositions a batch file's collection writes, on the path finalize runs.

Driven through ``collect_batch_rows`` against a real ``SQLiteBackend``: each record
was stamped ``deferred`` at submission, and collection must leave it holding the
same terminal disposition, reason, input snapshot and detail online writes. The
terminal disposition is written before ``deferred`` is cleared, so a process that
dies between the two leaves the record's outcome queryable rather than nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.services.collect import collect_batch_rows
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "my_action"
_WRITES = ("set_disposition", "set_dispositions_batch", "clear_disposition")


class _Crash(BaseException):
    """The process dying: no ``except Exception`` on the way out catches it."""


class _Recorder:
    """Records each disposition write on a real store, by the records it touches."""

    def __init__(self, backend: SQLiteBackend, *, crash_on_second_write_to: str | None = None):
        self.calls: list[tuple[str, str, str | None]] = []
        self._crash_for = crash_on_second_write_to
        for name in _WRITES:
            setattr(backend, name, self._wrap(name, getattr(backend, name)))

    def _wrap(self, name: str, real: Any) -> Any:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            touched = list(self._touched(name, args, kwargs))
            if self._crash_for and any(rid == self._crash_for for rid, _ in touched):
                if any(rid == self._crash_for for _, rid, _ in self.calls):
                    raise _Crash(f"died before {name} for {self._crash_for}")
            for record_id, disposition in touched:
                self.calls.append((name, record_id, disposition))
            return real(*args, **kwargs)

        return recorded

    @staticmethod
    def _touched(name: str, args: tuple, kwargs: dict) -> Any:
        if name == "set_dispositions_batch":
            for row in args[0]:
                yield row[1], row[2]
        elif name == "set_disposition":
            yield args[1], args[2]
        else:
            yield kwargs.get("record_id"), kwargs.get("disposition")

    def first(self, record_id: str, *, clearing: bool) -> int:
        return next(
            index
            for index, (name, rid, _disp) in enumerate(self.calls)
            if rid == record_id and (name == "clear_disposition") == clearing
        )


@pytest.fixture
def backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    return backend


def _entry(guid: str, status: str, skip_reason: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "source_guid": guid,
        "target_id": f"t-{guid}",
        "content": {"source": {"item": guid}},
        ContextMetaKeys.FILTER_STATUS: status,
    }
    if skip_reason:
        entry[ContextMetaKeys.SKIP_REASON] = skip_reason
    return entry


def _deferred(backend: SQLiteBackend, *guids: str) -> None:
    for guid in guids:
        backend.set_disposition(ACTION, guid, "deferred", reason="batch_queued:batch_id=b1")


def _exhausted_after(attempts: int) -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(attempts=attempts, failures=attempts, succeeded=False, reason="missing")
    )


# One record per outcome collection settles; each was stamped deferred at submission.
OUTCOMES = {
    "success": (
        _entry("r1", "included"),
        [BatchResult(custom_id="t-r1", content={"answer": "ok"}, success=True)],
        {},
        "success",
    ),
    "failed": (
        _entry("r1", "included"),
        [BatchResult(custom_id="t-r1", content=None, success=False, error="provider 500")],
        {},
        "failed",
    ),
    "exhausted": (
        _entry("r1", "included"),
        [],
        {"t-r1": _exhausted_after(3)},
        "exhausted",
    ),
    "guard_skipped": (_entry("r1", "skipped", "guard_skip"), [], {}, "unprocessed"),
    "filtered": (_entry("r1", "filtered", "guard_filter"), [], {}, "filtered"),
}


def _collect(backend, context_map, results, exhausted=None, tmp_path=None):
    return collect_batch_rows(
        backend,
        ACTION,
        {"action_name": ACTION},
        context_map,
        results,
        output_directory=str(tmp_path),
        exhausted_recovery=exhausted or None,
    )


def _held(backend: SQLiteBackend) -> dict[str, dict[str, Any]]:
    return {row["record_id"]: row for row in backend.get_disposition(ACTION)}


class TestTheTerminalDispositionIsWrittenBeforeDeferredIsCleared:
    @pytest.mark.parametrize("outcome", list(OUTCOMES))
    def test_each_outcome_writes_its_disposition_before_clearing_deferred(
        self, backend, tmp_path, outcome
    ):
        entry, results, exhausted, expected = OUTCOMES[outcome]
        _deferred(backend, "r1")
        recorder = _Recorder(backend)

        _collect(backend, {entry["target_id"]: entry}, results, exhausted, tmp_path)

        assert recorder.first("r1", clearing=False) < recorder.first("r1", clearing=True), (
            f"deferred was cleared before the {expected} disposition was written: {recorder.calls}"
        )
        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {"r1": expected}

    @pytest.mark.parametrize("outcome", list(OUTCOMES))
    def test_dying_between_the_two_writes_leaves_the_outcome_queryable(
        self, backend, tmp_path, outcome
    ):
        entry, results, exhausted, expected = OUTCOMES[outcome]
        _deferred(backend, "r1")
        _Recorder(backend, crash_on_second_write_to="r1")

        with pytest.raises(_Crash):
            _collect(backend, {entry["target_id"]: entry}, results, exhausted, tmp_path)

        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {
            "r1": expected
        }, "the record was left holding nothing"

    def test_each_of_several_records_is_settled_before_its_own_deferred_is_cleared(
        self, backend, tmp_path
    ):
        context_map = {
            "t-a": _entry("a", "included"),
            "t-b": _entry("b", "included"),
            "t-c": _entry("c", "included"),
        }
        _deferred(backend, "a", "b", "c")
        recorder = _Recorder(backend)

        _collect(
            backend,
            context_map,
            [
                BatchResult(custom_id="t-a", content=None, success=False, error="err a"),
                BatchResult(custom_id="t-c", content={"answer": "ok"}, success=True),
            ],
            {"t-b": _exhausted_after(2)},
            tmp_path,
        )

        for guid in ("a", "b", "c"):
            assert recorder.first(guid, clearing=False) < recorder.first(guid, clearing=True)
        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {
            "a": "failed",
            "b": "exhausted",
            "c": "success",
        }


class TestTheDispositionsMatchWhatOnlineWrites:
    def test_every_answered_record_holds_success(self, backend, tmp_path):
        context_map = {"t-a": _entry("a", "included"), "t-b": _entry("b", "included")}
        _deferred(backend, "a", "b")

        _collect(
            backend,
            context_map,
            [
                BatchResult(custom_id="t-a", content={"answer": "1"}, success=True),
                BatchResult(custom_id="t-b", content={"answer": "2"}, success=True),
            ],
            tmp_path=tmp_path,
        )

        held = _held(backend)
        assert {rid: row["disposition"] for rid, row in held.items()} == {
            "a": "success",
            "b": "success",
        }
        assert [held[g]["input_snapshot"] for g in ("a", "b")] == [None, None]

    def test_a_filtered_record_holds_filtered_with_its_reason(self, backend, tmp_path):
        context_map = {
            "t-f": _entry("f", "filtered", "guard_filter"),
            "t-i": _entry("i", "included"),
        }
        _deferred(backend, "i")

        _collect(
            backend,
            context_map,
            [BatchResult(custom_id="t-i", content={"answer": "ok"}, success=True)],
            tmp_path=tmp_path,
        )

        held = _held(backend)
        assert (held["f"]["disposition"], held["f"]["reason"]) == ("filtered", "guard_filter")
        assert held["i"]["disposition"] == "success"

    def test_a_guard_skipped_record_holds_unprocessed_with_its_reason(self, backend, tmp_path):
        context_map = {"t-k": _entry("k", "skipped", "guard_skip")}

        _collect(backend, context_map, [], tmp_path=tmp_path)

        held = _held(backend)["k"]
        assert (held["disposition"], held["reason"]) == ("unprocessed", "guard_skip")

    def test_a_failed_record_holds_its_input_and_the_error(self, backend, tmp_path):
        context_map = {"t-r1": _entry("r1", "included")}
        _deferred(backend, "r1")

        _collect(
            backend,
            context_map,
            [
                BatchResult(
                    custom_id="t-r1", content=None, success=False, error="model timeout after 30s"
                )
            ],
            tmp_path=tmp_path,
        )

        held = _held(backend)["r1"]
        assert held["disposition"] == "failed"
        assert held["reason"] == "model timeout after 30s"
        assert held["detail"] == "model timeout after 30s"
        snapshot = json.loads(held["input_snapshot"])
        assert snapshot["source_guid"] == "r1"
        assert snapshot["content"] == {"source": {"item": "r1"}}

    def test_an_exhausted_record_holds_its_input_and_the_cause(self, backend, tmp_path):
        context_map = {"t-r1": _entry("r1", "included")}
        _deferred(backend, "r1")

        _collect(backend, context_map, [], {"t-r1": _exhausted_after(3)}, tmp_path)

        held = _held(backend)["r1"]
        assert held["disposition"] == "exhausted"
        assert held["reason"] == "exhausted_after_3_attempts"
        assert held["detail"], "the exhaustion's cause was not recorded"
        snapshot = json.loads(held["input_snapshot"])
        assert snapshot["source_guid"] == "r1"
        assert snapshot["content"] == {"source": {"item": "r1"}}


class TestARecordWithNoIdentity:
    def test_it_is_warned_of_and_the_others_are_still_settled(self, backend, tmp_path, caplog):
        nameless = {
            "target_id": "t-x",
            "content": {"source": {}},
            ContextMetaKeys.FILTER_STATUS: "included",
        }
        context_map = {"t-x": nameless, "t-a": _entry("a", "included")}
        _deferred(backend, "a")

        with caplog.at_level(logging.WARNING, logger="agent_actions.processing.result_collector"):
            _collect(
                backend,
                context_map,
                [
                    BatchResult(custom_id="t-x", content={"answer": "x"}, success=True),
                    BatchResult(custom_id="t-a", content={"answer": "a"}, success=True),
                ],
                tmp_path=tmp_path,
            )

        assert any(
            "no source_guid" in record.getMessage()
            and "disposition not written" in record.getMessage()
            for record in caplog.records
        ), [record.getMessage() for record in caplog.records]
        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {"a": "success"}


class TestAFileThatThrewMarksItsRecordsFailedBeforeClearingDeferred:
    """The other place a batch clears ``deferred``: a file whose processing raised."""

    @staticmethod
    def _service(backend: SQLiteBackend) -> BatchProcessingService:
        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            storage_backend=backend,
            workflow_name=ACTION,
        )
        service._context_manager.load_batch_context_map.return_value = {
            "t-r1": {ContextMetaKeys.FILTER_STATUS: str(FilterStatus.INCLUDED), "source_guid": "r1"}
        }
        return service

    def test_failed_is_written_before_deferred_is_cleared(self, backend):
        _deferred(backend, "r1")
        service = self._service(backend)
        recorder = _Recorder(backend)

        service._fail_abandoned_records("f.json", "/unused", ACTION, RuntimeError("boom"))

        assert recorder.first("r1", clearing=False) < recorder.first("r1", clearing=True), (
            recorder.calls
        )
        assert _held(backend)["r1"]["disposition"] == "failed"

    def test_dying_between_the_two_writes_leaves_the_record_queryable(self, backend):
        _deferred(backend, "r1")
        service = self._service(backend)
        _Recorder(backend, crash_on_second_write_to="r1")

        with pytest.raises(_Crash):
            service._fail_abandoned_records("f.json", "/unused", ACTION, RuntimeError("boom"))

        assert _held(backend)["r1"]["disposition"] == "failed"


class _StoreError(Exception):
    """A store error on a terminal disposition write; clearing ``deferred`` still works."""


def _failing_terminal_writes(backend: SQLiteBackend, *, only: str | None = None) -> None:
    """Make every terminal disposition write raise, or only those for record *only*."""
    real_one, real_many = backend.set_disposition, backend.set_dispositions_batch

    def one(action, record_id, disposition, *args, **kwargs):
        if disposition != "deferred" and only in (None, record_id):
            raise _StoreError(f"disk I/O error writing {disposition} for {record_id}")
        return real_one(action, record_id, disposition, *args, **kwargs)

    def many(rows):
        if any(row[2] != "deferred" and only in (None, row[1]) for row in rows):
            raise _StoreError("disk I/O error writing a batch of dispositions")
        return real_many(rows)

    backend.set_disposition = one
    backend.set_dispositions_batch = many


class TestAFailedTerminalWriteKeepsDeferred:
    """A record whose terminal disposition was not stored keeps ``deferred`` (1519).

    Clearing it anyway left the record holding no disposition at all.
    """

    @pytest.mark.parametrize("outcome", list(OUTCOMES))
    def test_the_record_still_holds_deferred(self, backend, tmp_path, outcome):
        entry, results, exhausted, _expected = OUTCOMES[outcome]
        _deferred(backend, "r1")
        _failing_terminal_writes(backend)

        _collect(backend, {entry["target_id"]: entry}, results, exhausted, tmp_path)

        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {
            "r1": "deferred"
        }, "the record was left holding no disposition"

    def test_only_the_record_whose_write_failed_keeps_it(self, backend, tmp_path):
        context_map = {
            "t-f": _entry("f", "filtered", "guard_filter"),
            "t-i": _entry("i", "included"),
        }
        _deferred(backend, "f", "i")
        _failing_terminal_writes(backend, only="f")

        _collect(
            backend,
            context_map,
            [BatchResult(custom_id="t-i", content={"answer": "ok"}, success=True)],
            tmp_path=tmp_path,
        )

        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {
            "f": "deferred",
            "i": "success",
        }

    def test_a_file_that_threw_keeps_deferred_when_failed_is_not_stored(self, backend):
        _deferred(backend, "r1")
        service = TestAFileThatThrewMarksItsRecordsFailedBeforeClearingDeferred._service(backend)
        _failing_terminal_writes(backend)

        service._fail_abandoned_records("f.json", "/unused", ACTION, RuntimeError("boom"))

        assert {rid: row["disposition"] for rid, row in _held(backend).items()} == {
            "r1": "deferred"
        }
