"""Every model call's usage is added to a sum for its action, kind, pricing and model.

`record_usage` is the one place an online call is counted, and `record_batch` the one place
a batch's results are. Neither names a vendor or a feature: the action is the ledger the
executor opened, and the kind is whatever `counted_as` says is in force.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from concurrent.futures import ThreadPoolExecutor

from agent_actions.llm.providers import usage_tracker
from agent_actions.llm.providers.usage_tracker import (
    UsageLedger,
    accounting,
    counted_as,
    prompt_and_completion,
    record_batch,
    record_usage,
    stored_usage,
    summarised,
)

ONE_CALL = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 20,
}


class Store:
    """The metadata calls the ledger makes, kept in a dict."""

    def __init__(self) -> None:
        self.meta: dict[str, str] = {}

    def save_metadata(self, key: str, value: str) -> None:
        self.meta[key] = value

    def load_metadata(self, key: str) -> str | None:
        return self.meta.get(key)

    def list_metadata_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self.meta if key.startswith(prefix))


def _row(kind: str, calls: int, *, batch: bool = False, model: str = "m") -> dict:
    return {
        "kind": kind,
        "batch": batch,
        "model": model,
        "calls": calls,
        **{field: count * calls for field, count in ONE_CALL.items()},
    }


def test_a_call_made_outside_an_action_is_counted_nowhere():
    ledger = UsageLedger("summarize")

    record_usage(ONE_CALL, model="m")
    with accounting(ledger):
        pass
    record_usage(ONE_CALL, model="m")

    assert ledger.rows() == []


def test_calls_are_summed_per_kind_pricing_and_model():
    ledger = UsageLedger("summarize")

    with accounting(ledger):
        record_usage(ONE_CALL, model="m")
        record_usage(ONE_CALL, model="m")
        record_usage(ONE_CALL, model="other")
        with counted_as("repair"):
            record_usage(ONE_CALL, model="m")
        record_batch("batch-1", ONE_CALL, calls=1, kind="main", model="m")

    assert ledger.rows() == [
        _row("main", 2),
        _row("main", 1, model="other"),
        _row("main", 1, batch=True),
        _row("repair", 1),
    ]


def test_calls_made_by_many_record_threads_at_once_all_reach_the_sum():
    ledger = UsageLedger("summarize")

    def one_record() -> None:
        for _ in range(200):
            record_usage(ONE_CALL, model="m")

    with accounting(ledger), ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(contextvars.copy_context().run, one_record) for _ in range(8)]
        for future in futures:
            future.result()

    assert ledger.rows() == [_row("main", 1600)]


def test_two_actions_running_at_once_each_keep_their_own_sum():
    first, second = UsageLedger("first"), UsageLedger("second")

    async def run(ledger: UsageLedger, calls: int) -> None:
        with accounting(ledger):
            for _ in range(calls):
                await asyncio.sleep(0)
                await asyncio.to_thread(record_usage, ONE_CALL, model="m")

    async def both() -> None:
        await asyncio.gather(run(first, 3), run(second, 5))

    asyncio.run(both())

    assert (first.rows(), second.rows()) == ([_row("main", 3)], [_row("main", 5)])


def test_the_kind_in_force_is_the_innermost_and_ends_with_its_block():
    ledger = UsageLedger("summarize")

    with accounting(ledger):
        with counted_as("repair"):
            with counted_as("judge"):
                record_usage(ONE_CALL, model="m")
            record_usage(ONE_CALL, model="m")
        record_usage(ONE_CALL, model="m")

    assert ledger.rows() == [_row("main", 1), _row("repair", 1), _row("judge", 1)]


def test_a_kind_the_tracker_has_never_heard_of_is_summed_under_its_name():
    ledger = UsageLedger("summarize")

    with accounting(ledger), counted_as("echo"):
        record_usage(ONE_CALL, model="m")
    with accounting(ledger):
        record_batch("batch-1", ONE_CALL, calls=4, kind="echo", model="m")

    assert [(row["kind"], row["batch"], row["calls"]) for row in ledger.rows()] == [
        ("echo", False, 1),
        ("echo", True, 4),
    ]


def test_a_call_with_no_model_is_summed_under_unknown():
    ledger = UsageLedger("summarize")

    with accounting(ledger):
        record_usage(ONE_CALL, model=None)

    assert [row["model"] for row in ledger.rows()] == ["unknown"]


def test_the_summary_gives_the_five_fields_and_the_rows_they_sum():
    rows = [_row("main", 2), _row("judge", 3, batch=True)]

    assert summarised(rows) == {
        "calls": 5,
        "input_tokens": 50,
        "output_tokens": 25,
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 100,
        "by_kind": [_row("main", 2), _row("judge", 3, batch=True)],
    }


def test_the_run_line_counts_the_whole_prompt_cached_or_not():
    assert prompt_and_completion([_row("main", 1)]) == {
        "input_tokens": 130,
        "output_tokens": 5,
        "total_tokens": 135,
    }
    assert prompt_and_completion([]) is None


class TestTheStore:
    def test_a_runs_online_calls_are_stored_under_the_run(self):
        store = Store()
        ledger = UsageLedger("summarize", "run-1", store)

        with accounting(ledger):
            record_usage(ONE_CALL, model="m")
            record_usage(ONE_CALL, model="m")
        ledger.save()

        assert stored_usage(store) == [
            {"action": "summarize", "run_id": "run-1", "rows": [_row("main", 2)]}
        ]

    def test_saving_again_replaces_the_runs_sum_and_does_not_add_to_it(self):
        store = Store()
        ledger = UsageLedger("summarize", "run-1", store)

        with accounting(ledger):
            record_usage(ONE_CALL, model="m")
            ledger.save()
            record_usage(ONE_CALL, model="m")
            ledger.save()
            ledger.save()

        (entry,) = stored_usage(store)
        assert entry["rows"] == [_row("main", 2)]

    def test_a_long_action_is_stored_while_it_runs(self, monkeypatch):
        monkeypatch.setattr(usage_tracker, "_SAVE_EVERY_SECONDS", 0.0)
        store = Store()

        with accounting(UsageLedger("summarize", "run-1", store)):
            record_usage(ONE_CALL, model="m")
            record_batch("batch-1", ONE_CALL, calls=1, kind="judge", model="m")

        by_source = {entry.get("batch_id"): entry["rows"] for entry in stored_usage(store)}
        assert by_source == {None: [_row("main", 1)], "batch-1": [_row("judge", 1, batch=True)]}

    def test_each_run_of_one_action_keeps_its_own_entry(self):
        store = Store()
        for run_id, calls in (("run-1", 1), ("run-2", 3)):
            ledger = UsageLedger("summarize", run_id, store)
            with accounting(ledger):
                for _ in range(calls):
                    record_usage(ONE_CALL, model="m")
            ledger.save()

        assert {entry["run_id"]: entry["rows"][0]["calls"] for entry in stored_usage(store)} == {
            "run-1": 1,
            "run-2": 3,
        }

    def test_a_batch_is_stored_as_it_is_counted_under_its_id(self):
        store = Store()

        with accounting(UsageLedger("summarize", "run-1", store)):
            record_batch("batch-1", ONE_CALL, calls=2, kind="judge", model="m")

        assert stored_usage(store) == [
            {
                "action": "summarize",
                "run_id": "run-1",
                "batch_id": "batch-1",
                "rows": [{**_row("judge", 1, batch=True), "calls": 2}],
            }
        ]

    def test_a_batch_read_twice_in_one_run_is_counted_once(self):
        ledger = UsageLedger("summarize", "run-1", Store())

        with accounting(ledger):
            record_batch("batch-1", ONE_CALL, calls=2, kind="main", model="m")
            record_batch("batch-1", ONE_CALL, calls=2, kind="main", model="m")

        assert [row["calls"] for row in ledger.rows()] == [2]

    def test_a_batch_a_later_run_reads_again_stays_with_the_run_that_read_it_first(self):
        store = Store()
        first = UsageLedger("summarize", "run-1", store)
        with accounting(first):
            record_batch("batch-1", ONE_CALL, calls=2, kind="main", model="m")

        resumed = UsageLedger("summarize", "run-2", store)
        with accounting(resumed):
            record_batch("batch-1", ONE_CALL, calls=2, kind="main", model="m")
            record_batch("batch-2", ONE_CALL, calls=1, kind="judge", model="m")
        resumed.save()

        assert [row["kind"] for row in resumed.rows()] == ["judge"]
        assert sorted((entry["batch_id"], entry["run_id"]) for entry in stored_usage(store)) == [
            ("batch-1", "run-1"),
            ("batch-2", "run-2"),
        ]

    def test_a_batch_with_no_answered_line_is_not_an_entry(self):
        store = Store()

        with accounting(UsageLedger("summarize", "run-1", store)):
            record_batch("batch-1", dict.fromkeys(ONE_CALL, 0), calls=0, kind="main", model="m")

        assert stored_usage(store) == []

    def test_a_run_with_no_id_is_counted_and_not_stored(self):
        store = Store()
        ledger = UsageLedger("summarize", None, store)

        with accounting(ledger):
            record_usage(ONE_CALL, model="m")
            record_batch("batch-1", ONE_CALL, calls=1, kind="main", model="m")
        ledger.save()

        assert [row["calls"] for row in ledger.rows()] == [1, 1]
        assert store.meta == {}

    def test_a_store_that_refuses_the_write_does_not_stop_the_call(self, caplog):
        class Refusing(Store):
            def save_metadata(self, key: str, value: str) -> None:
                raise OSError("disk full")

        ledger = UsageLedger("summarize", "run-1", Refusing())

        with accounting(ledger):
            record_usage(ONE_CALL, model="m")
            record_batch("batch-1", ONE_CALL, calls=1, kind="main", model="m")
        ledger.save()

        assert [row["calls"] for row in ledger.rows()] == [1, 1]
        assert "Could not store the token usage of summarize: disk full" in caplog.text

    def test_an_entry_that_cannot_be_read_is_left_out_and_said(self, caplog):
        store = Store()
        store.meta["usage:summarize:run:run-0"] = "not json"
        store.meta["usage:summarize:run:run-1"] = json.dumps(
            {"action": "summarize", "run_id": "run-1", "rows": [_row("main", 1)]}
        )

        assert [entry["run_id"] for entry in stored_usage(store)] == ["run-1"]
        assert "usage:summarize:run:run-0 cannot be read" in caplog.text
