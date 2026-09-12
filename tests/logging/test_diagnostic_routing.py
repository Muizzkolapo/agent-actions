"""Framework-internal diagnostics stay out of the terminal but keep full log-file fidelity.

``ConsoleEventHandler`` shows every WARN and ERROR regardless of category, so
framework internals reach the terminal alongside messages the user can act on.
Demoting those call sites to ``debug`` would hide them from the log file too;
marking them diagnostic suppresses the console line and leaves the WARN intact
everywhere else.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.core.handlers import ConsoleEventHandler, JSONFileHandler
from agent_actions.logging.core.handlers.bridge import LoggingBridgeHandler
from agent_actions.logging.core.manager import EventManager
from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.logging.factory import LoggerFactory


class _Capture:
    def __init__(self):
        self.events: list[BaseEvent] = []

    def accepts(self, event: BaseEvent) -> bool:
        return True

    def handle(self, event: BaseEvent) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


def _console(**kwargs) -> ConsoleEventHandler:
    kwargs.setdefault("min_level", EventLevel.INFO)
    kwargs.setdefault("categories", {"workflow", "action", "batch"})
    return ConsoleEventHandler(**kwargs)


def _event(level: EventLevel, category: str, *, diagnostic: bool) -> BaseEvent:
    return BaseEvent(level=level, category=category, message="m", diagnostic=diagnostic)


class TestConsoleSuppressesDiagnostics:
    def test_a_diagnostic_warn_is_kept_off_the_console(self):
        assert _console().accepts(_event(EventLevel.WARN, "prompt", diagnostic=True)) is False

    def test_a_diagnostic_error_is_kept_off_the_console(self):
        assert _console().accepts(_event(EventLevel.ERROR, "processing", diagnostic=True)) is False

    def test_a_plain_warn_from_the_same_category_still_reaches_the_console(self):
        assert _console().accepts(_event(EventLevel.WARN, "prompt", diagnostic=False)) is True

    def test_verbose_consoles_show_diagnostics(self):
        handler = _console(min_level=EventLevel.DEBUG, categories=None, show_diagnostics=True)

        assert handler.accepts(_event(EventLevel.WARN, "prompt", diagnostic=True)) is True

    def test_a_diagnostic_below_min_level_is_still_rejected(self):
        assert _console().accepts(_event(EventLevel.DEBUG, "prompt", diagnostic=True)) is False


class TestLogFileKeepsFullFidelity:
    def test_the_events_file_accepts_a_diagnostic_warn(self, tmp_path):
        handler = JSONFileHandler(file_path=tmp_path / "events.json", min_level=EventLevel.DEBUG)

        assert handler.accepts(_event(EventLevel.WARN, "prompt", diagnostic=True)) is True

    def test_the_errors_file_accepts_a_diagnostic_error(self, tmp_path):
        handler = JSONFileHandler(file_path=tmp_path / "errors.json", min_level=EventLevel.ERROR)

        assert handler.accepts(_event(EventLevel.ERROR, "prompt", diagnostic=True)) is True

    def test_a_diagnostic_warn_serializes_at_warn_level(self):
        serialized = _event(EventLevel.WARN, "prompt", diagnostic=True).to_dict()

        assert serialized["level"] == "warn"
        assert serialized["diagnostic"] is True

    def test_an_ordinary_event_serializes_as_not_diagnostic(self):
        assert BaseEvent(message="m").to_dict()["diagnostic"] is False


class TestTheBridgeCarriesTheMarker:
    @pytest.fixture(autouse=True)
    def _manager(self):
        EventManager.reset()
        yield
        EventManager.reset()

    def _emit(self, extra: dict | None) -> BaseEvent:
        capture = _Capture()
        EventManager.get().register(capture)
        log = logging.getLogger("agent_actions.prompt.test_diagnostic_routing")
        log.setLevel(logging.DEBUG)
        log.handlers = [LoggingBridgeHandler()]
        log.propagate = False
        log.warning("internal detail", extra=extra or {})

        assert capture.events, "no event reached the manager"
        return capture.events[-1]

    def test_extra_diagnostic_marks_the_event(self):
        assert self._emit(DIAGNOSTIC).diagnostic is True

    def test_a_plain_warning_is_not_diagnostic(self):
        assert self._emit(None).diagnostic is False

    def test_the_marker_does_not_also_land_in_the_payload(self):
        assert "diagnostic" not in self._emit(DIAGNOSTIC).data

    def test_other_extras_still_reach_the_payload(self):
        event = self._emit({**DIAGNOSTIC, "action_name": "review"})

        assert event.diagnostic is True
        assert event.data["action_name"] == "review"


def _registered_console() -> ConsoleEventHandler:
    manager = EventManager.get()
    consoles = [h for h in manager._handlers if isinstance(h, ConsoleEventHandler)]
    assert len(consoles) == 1, f"expected one console handler, got {len(consoles)}"
    return consoles[0]


class TestFactoryWiring:
    def test_the_default_console_hides_diagnostics(self):
        LoggerFactory.initialize(force=True)

        assert _registered_console().show_diagnostics is False

    def test_a_verbose_console_shows_diagnostics(self):
        LoggerFactory.initialize(verbose=True, force=True)

        assert _registered_console().show_diagnostics is True


class TestVerbositySurvivesReinitialization:
    """``agac run`` re-initializes with ``force=True`` to attach the run's file
    handlers, passing no verbosity. That must not discard the CLI's flags."""

    def test_verbose_survives_a_reinitialization_that_omits_it(self, tmp_path):
        LoggerFactory.initialize(verbose=True, force=True)

        LoggerFactory.initialize(output_dir=tmp_path, workflow_name="w", force=True)

        console = _registered_console()
        assert console.min_level == EventLevel.DEBUG
        assert console.categories is None
        assert console.show_diagnostics is True

    def test_quiet_survives_a_reinitialization_that_omits_it(self, tmp_path):
        LoggerFactory.initialize(quiet=True, force=True)

        LoggerFactory.initialize(output_dir=tmp_path, workflow_name="w", force=True)

        assert _registered_console().min_level == EventLevel.WARN

    def test_an_explicit_verbose_false_overrides_the_remembered_value(self, tmp_path):
        LoggerFactory.initialize(verbose=True, force=True)

        LoggerFactory.initialize(output_dir=tmp_path, verbose=False, force=True)

        assert _registered_console().show_diagnostics is False

    def test_reset_forgets_the_remembered_verbosity(self):
        LoggerFactory.initialize(verbose=True, force=True)
        LoggerFactory.reset()

        LoggerFactory.initialize()

        assert _registered_console().show_diagnostics is False


def _warns_from(run, tmp_path) -> list[BaseEvent]:
    """Run framework code with real logging wired up; return its WARN events."""
    LoggerFactory.initialize(output_dir=tmp_path, workflow_name="w", force=True)
    capture = _Capture()
    EventManager.get().register(capture)
    run()
    return [e for e in capture.events if e.level is EventLevel.WARN]


def _assert_kept_off_the_console(events: list[BaseEvent], fragment: str) -> None:
    matching = [e for e in events if fragment in e.message]
    assert matching, f"no WARN event mentioning {fragment!r}; got {[e.message for e in events]}"
    console = _registered_console()
    for event in matching:
        assert event.diagnostic is True, f"not marked diagnostic: {event.message}"
        assert console.accepts(event) is False, f"reached the console: {event.message}"


class TestScopeBuilderDiagnostics:
    def test_a_zero_overlap_namespace_is_kept_off_the_console(self, tmp_path):
        from agent_actions.prompt.context.scope_builder import build_field_context_with_history

        def run():
            build_field_context_with_history(
                agent_name="review",
                agent_config={"dependencies": ["generate_quiz"]},
                agent_indices={"generate_quiz": 0, "review": 1},
                current_item={
                    "content": {"generate_quiz": {"foo": 1}},
                    "lineage": ["node-1"],
                    "source_guid": "sg-1",
                },
                context_scope={"observe": ["generate_quiz.answer"]},
            )

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "zero overlap")

    def test_a_non_dict_namespace_is_kept_off_the_console(self, tmp_path):
        from agent_actions.prompt.context.scope_builder import build_field_context_with_history

        def run():
            build_field_context_with_history(
                agent_name="review",
                agent_config={"dependencies": ["generate_quiz"]},
                agent_indices={"generate_quiz": 0, "review": 1},
                current_item={
                    "content": {"generate_quiz": "not a dict"},
                    "lineage": ["node-1"],
                    "source_guid": "sg-1",
                },
                context_scope={"observe": ["generate_quiz.answer"]},
            )

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "not dict")


class TestEnrichmentDiagnostics:
    @staticmethod
    def _enrich(source_mapping):
        from agent_actions.processing.enrichment import LineageEnricher
        from agent_actions.processing.types import (
            ProcessingContext,
            ProcessingResult,
            ProcessingStatus,
        )

        def run():
            LineageEnricher().enrich(
                ProcessingResult(
                    status=ProcessingStatus.SUCCESS,
                    data=[{"content": {"val": 1}}],
                    source_guid=None,
                    source_mapping=source_mapping,
                ),
                ProcessingContext(
                    agent_config={"kind": "tool", "granularity": "file"},
                    agent_name="dedup_tool",
                    is_first_stage=False,
                    source_data=[
                        {
                            "source_guid": "guid-a",
                            "node_id": "node_0",
                            "lineage": ["node_0"],
                            "content": {"data": "x"},
                        }
                    ],
                ),
            )

        return run

    def test_a_one_to_one_index_overrun_is_kept_off_the_console(self, tmp_path):
        events = _warns_from(self._enrich({0: 5}), tmp_path)

        _assert_kept_off_the_console(events, "is out of bounds")

    def test_a_many_to_one_index_overrun_is_kept_off_the_console(self, tmp_path):
        events = _warns_from(self._enrich({0: [0, 5]}), tmp_path)

        _assert_kept_off_the_console(events, "indices out of bounds")


class TestScopeApplicationDiagnostics:
    def test_a_null_safe_field_resolution_is_kept_off_the_console(self, tmp_path):
        from agent_actions.prompt.context.scope_application import apply_context_scope

        def run():
            apply_context_scope(
                field_context={"dep": {"present": 1}},
                context_scope={"passthrough": ["dep.absent"]},
                action_name="consumer",
            )

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "NULL-SAFE")
