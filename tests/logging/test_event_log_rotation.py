"""events.json holds one workflow run; earlier runs rotate to events.N.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.handlers import JSONFileHandler
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.events.cache_events import CacheMissEvent
from agent_actions.logging.events.llm_events import LLMResponseEvent
from agent_actions.logging.factory import LoggerFactory
from agent_actions.tooling.docs.scanner.data_scanners import extract_run_events


@pytest.fixture(autouse=True)
def _fresh_factory(monkeypatch):
    monkeypatch.delenv("AGENT_ACTIONS_LOG_RETAIN_RUNS", raising=False)
    monkeypatch.delenv("AGENT_ACTIONS_LOG_MAX_BYTES", raising=False)
    LoggerFactory.reset()
    yield
    EventManager.get().flush()
    LoggerFactory.reset()


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _start(io_dir: Path, run_id: str | None, *, new_run: bool) -> None:
    LoggerFactory.initialize(
        output_dir=str(io_dir),
        workflow_name="wf",
        invocation_id=run_id,
        new_run=new_run,
        force=True,
    )
    EventManager.get().fire(BaseEvent(message=f"hello from {run_id}"))
    EventManager.get().flush()


def _run_ids(path: Path) -> set[str]:
    return {row["meta"]["invocation_id"] for row in _rows(path)}


class TestTheScannerSurvivesAnInfoFileLevel:
    def test_token_and_cache_metrics_are_written_by_an_info_handler(self, tmp_path):
        log = tmp_path / "events.json"
        handler = JSONFileHandler(file_path=log, min_level=EventLevel.INFO)
        for event in (
            LLMResponseEvent(action_name="a", prompt_tokens=7, completion_tokens=3, latency_ms=10),
            CacheMissEvent(cache_type="t", key="k"),
        ):
            assert handler.accepts(event)
            event.meta.extra["action_name"] = "a"
            handler.handle(event)
        handler.close()

        metrics = extract_run_events(log).action_metrics["a"]

        assert metrics["tokens"] == {"prompt_tokens": 7, "completion_tokens": 3}
        assert metrics["cache_miss_count"] == 1


class TestEachRunGetsItsOwnFile:
    def test_three_runs_leave_three_files_each_holding_one_run(self, tmp_path):
        for run_id in ("r1", "r2", "r3"):
            _start(tmp_path, run_id, new_run=True)

        logs = tmp_path / "logs"
        assert _run_ids(logs / "events.json") == {"r3"}
        assert _run_ids(logs / "events.1.json") == {"r2"}
        assert _run_ids(logs / "events.2.json") == {"r1"}

    def test_a_command_that_is_not_a_run_appends_to_the_current_file(self, tmp_path):
        _start(tmp_path, "r1", new_run=True)
        _start(tmp_path, "batch-status", new_run=False)
        _start(tmp_path, "r2", new_run=True)

        logs = tmp_path / "logs"
        assert _run_ids(logs / "events.json") == {"r2"}
        assert _run_ids(logs / "events.1.json") == {"r1", "batch-status"}
        assert not (logs / "events.2.json").exists()

    def test_runs_older_than_the_retention_are_deleted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_ACTIONS_LOG_RETAIN_RUNS", "2")
        for run_id in ("r1", "r2", "r3", "r4"):
            _start(tmp_path, run_id, new_run=True)

        logs = tmp_path / "logs"
        assert _run_ids(logs / "events.json") == {"r4"}
        assert _run_ids(logs / "events.2.json") == {"r2"}
        assert not (logs / "events.3.json").exists()

    def test_the_errors_file_rotates_with_the_events_file(self, tmp_path):
        for run_id in ("r1", "r2"):
            LoggerFactory.initialize(
                output_dir=str(tmp_path), invocation_id=run_id, new_run=True, force=True
            )
            EventManager.get().fire(BaseEvent(level=EventLevel.ERROR, message=run_id))
            EventManager.get().flush()

        logs = tmp_path / "logs"
        assert _run_ids(logs / "errors.json") == {"r2"}
        assert _run_ids(logs / "errors.1.json") == {"r1"}

    @pytest.mark.parametrize("value", ["0", "-1", "many"])
    def test_an_invalid_retention_is_reported_and_the_default_used(
        self, tmp_path, monkeypatch, capsys, value
    ):
        monkeypatch.setenv("AGENT_ACTIONS_LOG_RETAIN_RUNS", value)
        for run_id in [f"r{i}" for i in range(7)]:
            _start(tmp_path, run_id, new_run=True)

        assert (
            f"agent_actions: ignoring AGENT_ACTIONS_LOG_RETAIN_RUNS={value!r}: "
            "must be an integer >= 1; using 5"
        ) in capsys.readouterr().err
        assert (tmp_path / "logs" / "events.5.json").exists()
        assert not (tmp_path / "logs" / "events.6.json").exists()


class TestTheCapShedsDebugRowsOnly:
    def _fill(self, handler: JSONFileHandler, count: int, level: EventLevel) -> None:
        for i in range(count):
            handler.handle(BaseEvent(level=level, message=f"{level.value}-{i}" + "x" * 200))

    def test_below_the_cap_debug_rows_are_written(self, tmp_path):
        log = tmp_path / "events.json"
        handler = JSONFileHandler(file_path=log, buffer_size=1, max_debug_bytes=1_000_000)
        self._fill(handler, 5, EventLevel.DEBUG)
        handler.close()

        assert [row["level"] for row in _rows(log)] == ["debug"] * 5

    def test_past_the_cap_debug_is_dropped_info_kept_and_the_drop_announced_once(self, tmp_path):
        log = tmp_path / "events.json"
        handler = JSONFileHandler(file_path=log, buffer_size=1, max_debug_bytes=2_000)
        self._fill(handler, 50, EventLevel.DEBUG)
        self._fill(handler, 3, EventLevel.INFO)
        handler.close()

        rows = _rows(log)
        caps = [row for row in rows if row["event_type"] == "LogFileCapReachedEvent"]
        assert len(caps) == 1
        assert caps[0]["level"] == "warn"
        assert caps[0]["data"]["max_bytes"] == 2_000
        assert sum(row["level"] == "debug" for row in rows) < 50
        assert [row["message"][:6] for row in rows if row["level"] == "info"] == [
            "info-0",
            "info-1",
            "info-2",
        ]

    def test_the_cap_is_read_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_ACTIONS_LOG_MAX_BYTES", "2000")
        LoggerFactory.initialize(
            output_dir=str(tmp_path), invocation_id="r1", new_run=True, force=True
        )
        for _ in range(50):
            EventManager.get().fire(BaseEvent(level=EventLevel.DEBUG, message="x" * 200))
        EventManager.get().flush()

        rows = _rows(tmp_path / "logs" / "events.json")
        assert sum(row["event_type"] == "LogFileCapReachedEvent" for row in rows) == 1
