"""Preparing a batch says what it cost, and its memory grows with the requests, not the records.

A batch file's preparation logs its time, its records and the process's peak memory, and
every step closes with that peak, so an operator can see which step held the memory.
A record carries every namespace above the action; its request carries what the prompt
observes. Preparing more records adds about one request each, not one record (#1865).
"""

from __future__ import annotations

import gc
import logging
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_models import (
    BatchTaskPreparationStats,
    PreparedBatchTasks,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.logging.core.events import BaseEvent
from agent_actions.logging.core.manager import EventManager
from agent_actions.utils.memory import peak_rss_mb
from agent_actions.workflow.execution_events import fire_step_complete

ANCESTORS = 10
FIELD = 20_000


class _NoStorage:
    """A storage backend that keeps nothing it is handed."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "k")
    (tmp_path / "agent_config").mkdir()
    (tmp_path / "agent_config" / "wf.yml").write_text("name: wf\n")
    return {
        "agent_type": "summarise",
        "action_name": "summarise",
        "name": "summarise",
        "model_vendor": "openai",
        "model_name": "gpt-4.1",
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": True,
        "granularity": "record",
        "run_mode": "batch",
        "prompt": "Summarise {{ extract.title }}.",
        "schema": {"summary": "string"},
        "dependencies": ["extract"],
        "context_scope": {"observe": ["extract.title"]},
        "workflow_config_path": str(tmp_path / "agent_config" / "wf.yml"),
    }


def _records(n: int) -> list[dict[str, Any]]:
    """Records that carry, besides the title the prompt reads, every namespace above."""
    records = []
    for i in range(n):
        content: dict[str, Any] = {"extract": {"title": f"title {i}", "page": "p" * FIELD}}
        for k in range(ANCESTORS):
            content[f"step{k}"] = {"text": f"{i}:{k} " + "t" * FIELD}
        records.append({"target_id": f"t{i}", "source_guid": f"sg{i}", "content": content})
    return records


def _record_size() -> int:
    gc.collect()
    tracemalloc.start()
    try:
        record = _records(1)
        size = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    del record
    return size


@contextmanager
def _no_log_records() -> Iterator[None]:
    """No log record is made: a capture that keeps every record (pytest at DEBUG) would be counted."""
    before = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(before)


def _peak_of_preparing(config: dict[str, Any], n: int) -> int:
    data = _records(n)
    gc.collect()
    with _no_log_records():
        return _traced_peak_of_preparing(config, data)


def _traced_peak_of_preparing(config: dict[str, Any], data: list[dict[str, Any]]) -> int:
    n = len(data)
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        prepared = BatchTaskPreparator(
            action_indices={"extract": 0, "summarise": 1},
            dependency_configs={},
            storage_backend=_NoStorage(),
        ).prepare_tasks(agent_config=config, data=data, provider=OpenAIBatchClient(api_key="k"))
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert len(prepared.tasks) == n
    return peak


def test_each_prepared_record_adds_far_less_than_the_record_it_reads(config):
    _peak_of_preparing(config, 5)  # Imports and compiled templates are not the records'.

    per_record = (_peak_of_preparing(config, 60) - _peak_of_preparing(config, 20)) / 40

    # A record holds eleven namespaces of 20 KB; its request holds a title.
    assert per_record < _record_size() / 20, (per_record, _record_size())


def test_a_prepared_file_logs_its_time_records_and_peak_memory(caplog):
    stats = BatchTaskPreparationStats(total_items=3, included_items=2, filtered_items=1)
    preparator = MagicMock(spec=BatchTaskPreparator)
    preparator.prepare_tasks.return_value = PreparedBatchTasks(
        tasks=[{"custom_id": "t0"}, {"custom_id": "t1"}], context_map={}, stats=stats, config={}
    )
    service = BatchSubmissionService(
        task_preparator=preparator,
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        registry_manager_factory=MagicMock(),
    )

    with caplog.at_level(logging.INFO, logger="agent_actions.llm.batch.services.submission"):
        service.prepare_batch_tasks(
            {"action_name": "summarise"}, [{}, {}, {}], batch_name="pages.json"
        )

    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Prepared")]
    assert line.startswith("Prepared summarise/pages.json in ")
    assert "3 record(s), 2 task(s), 1 filtered" in line
    assert "peak memory " in line and line.endswith(" MB")


def test_a_closing_step_carries_the_peak_memory():
    events: list[BaseEvent] = []

    class _Capture:
        def accepts(self, event: BaseEvent) -> bool:
            return True

        def handle(self, event: BaseEvent) -> None:
            events.append(event)

        def flush(self) -> None:
            pass

    EventManager.reset()
    manager = EventManager.get()
    manager.clear_handlers()
    manager.register(_Capture())
    try:
        fire_step_complete(0, 1, 0.5, ["summarise"], MagicMock())
    finally:
        EventManager.reset()

    (step,) = [event for event in events if event.event_type == "StepCompleteEvent"]
    assert step.data["peak_rss_mb"] > 0
    assert step.data["peak_rss_mb"] <= (peak_rss_mb() or 0)
