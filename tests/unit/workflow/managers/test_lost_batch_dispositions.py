"""The disposition a collected batch record lost is read from its stored row (1524).

Over a real SQLite store, with the registry and rows a collect pass leaves once the store
refused the records' dispositions: each record still holds the ``deferred`` its submission
stamped. Only a record of a collected batch with a row in one settled state is answered.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.batch import lost_dispositions, settle_lost_dispositions

ACTION = "summarize"
BATCH = "batch-pages"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    return store


def _register(backend, file_name: str = "pages.json", *, collected: bool = True, batch=BATCH):
    BatchRegistryManager(backend, ACTION).save_batch_job(
        file_name,
        BatchJobEntry(
            batch_id=batch,
            status=BatchStatus.COMPLETED,
            timestamp="2026-10-18T09:00:00+00:00",
            provider="agac-provider",
            record_count=2,
            file_name=file_name,
            collected_at="2026-10-18T09:05:00+00:00" if collected else None,
        ),
    )


def _defer(backend, guid: str, batch: str = BATCH) -> None:
    backend.set_disposition(
        ACTION, guid, DISPOSITION_DEFERRED, reason=f"batch_queued:batch_id={batch}"
    )


def _row(guid: str, state: str, reason: str | None = None, **extra) -> dict:
    return {
        "source_guid": guid,
        "content": {ACTION: {"summary": guid}},
        "_state": state,
        "_state_history": [
            {"action": ACTION, "from": "active", "to": state, "reason": reason, "detail": None}
        ],
        "_delta_mode": "full",
        **extra,
    }


def _store(backend, *rows: dict) -> None:
    backend.write_target(ACTION, "pages.json", list(rows), force_full=True)


def _settled(backend) -> dict[str, tuple]:
    return {row[1]: (row[2], row[3]) for row in lost_dispositions(backend, ACTION)}


@pytest.mark.parametrize(
    ("state", "reason", "expected"),
    [
        ("processed", "success", (DISPOSITION_SUCCESS, None)),
        ("failed", "batch_not_returned", (DISPOSITION_FAILED, "batch_not_returned")),
        ("exhausted", "retry_exhausted", (DISPOSITION_EXHAUSTED, "retry_exhausted")),
        ("guard_skipped", "empty_output", (DISPOSITION_PASSTHROUGH, "empty_output")),
        (
            "cascade_skipped",
            "upstream_unprocessed",
            (DISPOSITION_UNPROCESSED, "upstream_unprocessed"),
        ),
    ],
)
def test_a_record_gets_what_its_row_stands_for(backend, state, reason, expected):
    _register(backend)
    _defer(backend, "g1")
    _store(backend, _row("g1", state, reason))

    assert _settled(backend) == {"g1": expected}


def test_a_split_record_is_answered_by_the_rows_it_produced(backend):
    _register(backend)
    _defer(backend, "g1")
    _store(
        backend,
        _row("g1-a", "processed", "success", producer_source_guids=["g1"]),
        _row("g1-b", "processed", "success", producer_source_guids=["g1"]),
    )

    assert _settled(backend) == {"g1": (DISPOSITION_SUCCESS, None)}


def test_nothing_is_answered_while_a_batch_is_still_to_collect(backend):
    _register(backend)
    _register(backend, "more.json", collected=False, batch="batch-more")
    _defer(backend, "g1")
    _store(backend, _row("g1", "processed", "success"))

    assert _settled(backend) == {}


def test_a_record_with_no_row_stays_deferred(backend):
    _register(backend)
    _defer(backend, "g1")
    _store(backend, _row("g2", "processed", "success"))

    assert _settled(backend) == {}


def test_a_deferred_naming_another_batch_is_left_alone(backend):
    _register(backend)
    _defer(backend, "g1", batch="batch-forgotten")
    _store(backend, _row("g1", "processed", "success"))

    assert _settled(backend) == {}


def test_a_record_holding_an_outcome_loses_only_the_stale_mark(backend):
    _register(backend)
    _defer(backend, "g1")
    backend.set_disposition(ACTION, "g1", DISPOSITION_FAILED, reason="parse_error")
    _store(backend, _row("g1", "processed", "success"))

    settled = lost_dispositions(backend, ACTION)
    settle_lost_dispositions(backend, settled)

    held = {row["disposition"] for row in backend.get_disposition(ACTION, record_id="g1")}
    assert held == {DISPOSITION_FAILED}


def test_settling_writes_the_outcome_and_clears_the_deferred(backend):
    _register(backend)
    _defer(backend, "g1")
    _defer(backend, "g2")
    _store(backend, _row("g1", "processed", "success"), _row("g2", "failed", "boom"))

    settle_lost_dispositions(backend, lost_dispositions(backend, ACTION))

    held = {row["record_id"]: row["disposition"] for row in backend.get_disposition(ACTION)}
    assert held == {"g1": DISPOSITION_SUCCESS, "g2": DISPOSITION_FAILED}
    assert lost_dispositions(backend, ACTION) == []
