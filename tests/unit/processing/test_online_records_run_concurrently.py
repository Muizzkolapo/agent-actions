"""Records of one online action run concurrently, up to `record_concurrency` at once.

The results come back in input order. Checkpoints, counts and progress stay on the
coordinating thread. A per-record error stays with its record, and an action-fatal error
stops the window. With the key unset, one record runs at a time, as before.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError, RecordContextError, is_action_fatal
from agent_actions.expectations.judge import JudgeBudget
from agent_actions.expectations.service import ExpectationsExhaustedError
from agent_actions.processing.strategies import online_llm
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus

LABEL: contextvars.ContextVar[str] = contextvars.ContextVar("label", default="none")


def _ok(item: dict[str, Any]) -> ProcessingResult:
    return ProcessingResult.success(data=[{"n": item["n"]}], source_guid=item["source_guid"])


class _Stub(OnlineLLMStrategy):
    """The real invoke loop over a stand-in for one record's answer."""

    def __init__(
        self,
        answer: Callable[[dict[str, Any]], ProcessingResult],
        concurrency: int | None,
        **config_extra: Any,
    ) -> None:
        config: dict[str, Any] = {"agent_type": "act", "name": "act", **config_extra}
        if concurrency is not None:
            config["record_concurrency"] = concurrency
        super().__init__(agent_config=config, agent_name="act", invocation_strategy=MagicMock())
        self._answer_one = answer
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak = 0
        self.started: list[int] = []

    def process_record(self, item: Any, context: Any, *, skip_guard: bool = False) -> Any:
        with self._lock:
            self._in_flight += 1
            self.peak = max(self.peak, self._in_flight)
            self.started.append(item["n"])
        try:
            return self._answer_one(item)
        finally:
            with self._lock:
                self._in_flight -= 1


class _Backend:
    """Records which thread wrote each checkpoint."""

    def __init__(self) -> None:
        self.writers: list[int] = []
        self.dispositions: list[str] = []

    def save_checkpoint_records(self, *args: Any) -> None:
        self.writers.append(threading.get_ident())

    def set_disposition(self, action: str, guid: str, disposition: str, **_: Any) -> None:
        self.writers.append(threading.get_ident())
        self.dispositions.append(guid)


def _records(count: int) -> list[dict[str, Any]]:
    return [{"n": i, "source_guid": f"g{i}"} for i in range(count)]


def _context(backend: _Backend | None = None) -> ProcessingContext:
    return ProcessingContext(
        agent_config={"agent_type": "act", "name": "act"},
        agent_name="act",
        storage_backend=backend,  # type: ignore[arg-type]
        target_relative_path="f.json" if backend else None,
    )


def test_four_records_are_in_flight_at_once():
    barrier = threading.Barrier(4, timeout=2)

    def answer(item: dict[str, Any]) -> ProcessingResult:
        barrier.wait()
        return _ok(item)

    strategy = _Stub(answer, concurrency=4)
    results = strategy.invoke(_records(4), _context())

    assert [r.status for r in results] == [ProcessingStatus.SUCCESS] * 4
    assert strategy.peak == 4


def test_unset_runs_one_record_at_a_time():
    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.01)
        return _ok(item)

    strategy = _Stub(answer, concurrency=None)
    results = strategy.invoke(_records(6), _context())

    assert len(results) == 6
    assert strategy.peak == 1


def test_no_more_than_the_limit_is_ever_in_flight():
    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.02)
        return _ok(item)

    strategy = _Stub(answer, concurrency=3)
    strategy.invoke(_records(12), _context())

    assert strategy.peak == 3


def test_results_come_back_in_input_order_when_completion_is_reversed():
    count = 5

    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.05 * (count - item["n"]))
        return _ok(item)

    results = _Stub(answer, concurrency=count).invoke(_records(count), _context())

    assert [r.data[0]["n"] for r in results] == list(range(count))


def test_a_record_with_incomplete_context_is_a_tombstone_at_its_own_index():
    def answer(item: dict[str, Any]) -> ProcessingResult:
        if item["n"] == 2:
            raise RecordContextError("missing observe field")
        return _ok(item)

    results = _Stub(answer, concurrency=4).invoke(_records(5), _context())

    assert [r.status for r in results] == [
        ProcessingStatus.SUCCESS,
        ProcessingStatus.SUCCESS,
        ProcessingStatus.FAILED,
        ProcessingStatus.SUCCESS,
        ProcessingStatus.SUCCESS,
    ]
    assert results[2].source_guid == "g2"


def test_an_action_fatal_error_stops_the_window():
    backend = _Backend()
    third_started = threading.Event()

    def answer(item: dict[str, Any]) -> ProcessingResult:
        if item["n"] == 2:
            # Fail only once record 3 holds the other slot of the window.
            assert third_started.wait(timeout=5)
            raise ConfigurationError("bad model")
        if item["n"] == 3:
            third_started.set()
            time.sleep(0.2)
        return _ok(item)

    strategy = _Stub(answer, concurrency=2)
    with pytest.raises(ConfigurationError) as excinfo:
        strategy.invoke(_records(10), _context(backend))

    assert is_action_fatal(excinfo.value)
    # Records 2 and 3 were the window when record 2 failed; nothing after them was sent.
    assert sorted(strategy.started) == [0, 1, 2, 3]
    assert {"g0", "g1"} <= set(backend.dispositions)


def test_an_exhaustion_halt_propagates_unchanged():
    def answer(item: dict[str, Any]) -> ProcessingResult:
        if item["n"] == 1:
            raise ExpectationsExhaustedError("act", ["g1"], 3)
        return _ok(item)

    with pytest.raises(ExpectationsExhaustedError):
        _Stub(answer, concurrency=3).invoke(_records(4), _context())


def test_every_checkpoint_is_written_on_the_coordinating_thread():
    backend = _Backend()

    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.01)
        return _ok(item)

    _Stub(answer, concurrency=4).invoke(_records(8), _context(backend))

    assert len(backend.dispositions) == 8
    assert set(backend.writers) == {threading.get_ident()}


def test_work_in_a_worker_sees_the_coordinators_context():
    seen: list[str] = []

    def answer(item: dict[str, Any]) -> ProcessingResult:
        seen.append(LABEL.get())
        return _ok(item)

    token = LABEL.set("act")
    try:
        _Stub(answer, concurrency=4).invoke(_records(4), _context())
    finally:
        LABEL.reset(token)

    assert seen == ["act"] * 4


def test_progress_counts_every_record_once(monkeypatch):
    events: list[Any] = []
    monkeypatch.setattr(online_llm, "fire_event", events.append)

    _Stub(_ok, concurrency=4).invoke(_records(10), _context())

    progress = [e for e in events if type(e).__name__ == "BatchProcessingProgressEvent"]
    assert progress[-1].processed == 10
    assert progress[-1].successes == 10


def test_a_judge_budget_grants_exactly_its_calls_across_threads():
    budget = JudgeBudget(3)
    start = threading.Barrier(16)
    granted: list[bool] = []

    def take() -> None:
        start.wait()
        granted.append(budget.try_acquire())

    threads = [threading.Thread(target=take) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert granted.count(True) == 3


def test_a_tool_action_that_inherited_the_key_runs_one_record_at_a_time():
    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.02)
        return _ok(item)

    strategy = _Stub(answer, concurrency=4, kind="tool", model_vendor="tool")
    strategy.invoke(_records(6), _context())

    assert strategy.peak == 1


def test_an_interrupt_keeps_the_answers_already_sent_and_sends_nothing_more(monkeypatch):
    backend = _Backend()
    real_wait = online_llm.wait
    calls: list[int] = []

    def interrupted_wait(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real_wait(*args, **kwargs)

    monkeypatch.setattr(online_llm, "wait", interrupted_wait)

    def answer(item: dict[str, Any]) -> ProcessingResult:
        time.sleep(0.05)
        return _ok(item)

    strategy = _Stub(answer, concurrency=3)
    with pytest.raises(KeyboardInterrupt):
        strategy.invoke(_records(12), _context(backend))

    assert len(strategy.started) < 12
    assert sorted(backend.dispositions) == sorted(f"g{n}" for n in strategy.started)
