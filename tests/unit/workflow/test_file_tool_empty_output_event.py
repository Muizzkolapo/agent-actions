"""FILE-mode empty output fires RecordEmptyOutputEvent, matching the online strategy."""

from __future__ import annotations

from typing import Any

from agent_actions.logging.core.events import BaseEvent
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.record.tracking import TrackedItem
from tests.unit.workflow.test_file_tool_on_empty_parity import _make_context


class _Spy:
    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


def _empties(spy: _Spy) -> list[RecordEmptyOutputEvent]:
    return [e for e in spy.events if isinstance(e, RecordEmptyOutputEvent)]


def _invoke_empty(on_empty: str, monkeypatch: Any) -> _Spy:
    records = [{"content": {"a": 1}}, {"content": {"a": 2}}]
    context = _make_context(on_empty)
    context.source_data = records

    monkeypatch.setattr(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        lambda **kwargs: ([], True),
    )

    spy = _Spy()
    manager = EventManager.get()
    manager.register(spy)
    try:
        FileToolStrategy().invoke(records, context)
    finally:
        manager.unregister(spy)
    return spy


def test_file_mode_empty_output_fires_record_empty_output_event(monkeypatch):
    spy = _invoke_empty("skip", monkeypatch)

    empties = _empties(spy)
    assert len(empties) == 1
    assert empties[0].on_empty == "skip"
    assert empties[0].input_field_count == 2
    assert empties[0].record_index == -1
    assert empties[0].action_name == "my_file_tool"


def test_file_mode_empty_output_event_carries_on_empty_warn(monkeypatch):
    spy = _invoke_empty("warn", monkeypatch)

    empties = _empties(spy)
    assert len(empties) == 1
    assert empties[0].on_empty == "warn"


def test_file_mode_non_empty_output_fires_no_empty_event(monkeypatch):
    records = [{"source_guid": "sg-1", "content": {"a": 1}}]
    context = _make_context("warn")
    context.source_data = records

    monkeypatch.setattr(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        lambda **kwargs: ([TrackedItem({"a": 1}, source_index=0)], True),
    )

    spy = _Spy()
    manager = EventManager.get()
    manager.register(spy)
    try:
        FileToolStrategy().invoke(records, context)
    finally:
        manager.unregister(spy)

    assert _empties(spy) == []
