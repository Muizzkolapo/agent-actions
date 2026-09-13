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
from agent_actions.logging.diagnostics import DIAGNOSTIC, DIAGNOSTIC_KEY
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
        assert DIAGNOSTIC_KEY not in self._emit(DIAGNOSTIC).data

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


class TestFrameworkMechanicsElsewhereAreDiagnostic:
    """Messages the user cannot act on, in modules beyond the first pass."""

    def test_the_state_history_cap_is_kept_off_the_console(self, tmp_path):
        from agent_actions.record.envelope import (
            _log_history_truncation_once,
            _reset_truncation_log_state_for_tests,
        )

        def run():
            _reset_truncation_log_state_for_tests()
            _log_history_truncation_once("review", dropped=3)

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "_state_history capped")

    def test_a_branch_missing_its_namespace_is_kept_off_the_console(self, tmp_path):
        from agent_actions.workflow.merge import merge_branch_records

        def run():
            merge_branch_records({"draft": {"content": {"unrelated": 1}}})

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "missing own namespace")

    def test_an_unresolved_source_guid_is_kept_off_the_console(self, tmp_path):
        from agent_actions.workflow.managers.loop import VersionOutputCorrelator

        records = {"v1": {"source_guid": None, "content": {"v1": {"answer": "a"}}}}

        def run():
            VersionOutputCorrelator(agent_folder=tmp_path)._create_merged_record(
                records, {k: [v] for k, v in records.items()}
            )

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "source_guid")


class TestUserAuthoredToolProblemsStayOnTheConsole:
    """A FILE tool is the user's own code, so its output problems are theirs to fix.

    These name an internal field but fail the criterion's actual test — the user
    can change the outcome — so they must survive any later sweep of the marker.
    """

    @staticmethod
    def _resolve(raw_outputs):
        from agent_actions.workflow.pipeline_file_mode import _resolve_source_mapping

        def run():
            _resolve_source_mapping(raw_outputs, [{"node_id": "n0", "content": {}}], "dedup_tool")

        return run

    def _assert_reaches_console(self, events, fragment):
        matching = [e for e in events if fragment in e.message]
        assert matching, f"no WARN mentioning {fragment!r}: {[e.message for e in events]}"
        console = _registered_console()
        for event in matching:
            assert event.diagnostic is False, f"wrongly marked diagnostic: {event.message}"
            assert console.accepts(event) is True, f"hidden from the user: {event.message}"

    def test_a_tool_output_without_a_node_id_still_reaches_the_console(self, tmp_path):
        events = _warns_from(self._resolve([{"content": {}}]), tmp_path)

        self._assert_reaches_console(events, "has no node_id")

    def test_a_tool_output_with_an_unknown_node_id_still_reaches_the_console(self, tmp_path):
        events = _warns_from(self._resolve([{"node_id": "ghost", "content": {}}]), tmp_path)

        self._assert_reaches_console(events, "not found in inputs")


class TestTheDocsSiteHonoursTheMarker:
    """The generated docs surface runtime warnings to the same person the console
    serves, so it must make the same distinction the console does."""

    @staticmethod
    def _collect(event: dict) -> list[dict]:
        from agent_actions.tooling.docs.scanner.data_scanners import _collect_runtime_warning

        warnings: list[dict] = []
        _collect_runtime_warning(event, warnings)
        return warnings

    def test_a_diagnostic_warning_is_not_surfaced(self):
        event = {"level": "warn", "message": "internal", "diagnostic": True, "meta": {}}

        assert self._collect(event) == []

    def test_an_ordinary_warning_is_still_surfaced(self):
        event = {"level": "warn", "message": "act on me", "diagnostic": False, "meta": {}}

        assert [w["message"] for w in self._collect(event)] == ["act on me"]

    def test_an_event_written_before_the_marker_existed_is_still_surfaced(self):
        assert len(self._collect({"level": "error", "message": "old line", "meta": {}})) == 1


class TestSiblingsOfMarkedSitesStayOnTheConsole:
    """A later sweep silencing a whole module would hide these."""

    def test_an_unreadable_merge_input_still_reaches_the_console(self, tmp_path):
        from agent_actions.workflow.merge import merge_json_files

        bad = tmp_path / "broken.json"
        bad.write_text("{not json")

        events = _warns_from(lambda: merge_json_files([bad]), tmp_path)
        matching = [e for e in events if "Could not read JSON file" in e.message]

        assert matching, f"no WARN for the unreadable file: {[e.message for e in events]}"
        console = _registered_console()
        for event in matching:
            assert event.diagnostic is False
            assert console.accepts(event) is True


class TestRemainingMechanicsInTheEditedModules:
    def test_a_vanished_target_listing_is_kept_off_the_console(self, tmp_path):
        from agent_actions.workflow.managers.loop import VersionOutputCorrelator

        class _RacingBackend:
            def list_target_files(self, version_agent):
                return ["gone.json"]

            def read_target(self, version_agent, relative_path):
                raise FileNotFoundError(relative_path)

        def run():
            VersionOutputCorrelator(
                agent_folder=tmp_path, storage_backend=_RacingBackend()
            )._load_from_storage_backend("v1")

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "TOCTOU")

    def test_a_duplicate_target_id_is_kept_off_the_console(self, tmp_path):
        from agent_actions.processing.invocation.batch import BatchStrategy
        from agent_actions.processing.prepared_task import PreparedTask
        from agent_actions.processing.types import ProcessingContext

        task = PreparedTask(target_id="t-1", source_guid="sg-1")
        context = ProcessingContext(
            agent_config={"kind": "llm"}, agent_name="score", is_first_stage=True, source_data=[]
        )

        def run():
            strategy = BatchStrategy(provider=None)
            strategy.invoke(task, context)
            strategy.invoke(task, context)

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "Duplicate target_id")


class TestStorageMechanicsAreDiagnostic:
    """Storage messages describing the framework's own bookkeeping."""

    @staticmethod
    def _backend(tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "quiz")
        backend.initialize()
        return backend

    def test_a_capability_gap_in_the_backend_is_kept_off_the_console(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        class _NoBatch(SQLiteBackend):
            def set_dispositions_batch(self, rows):
                raise NotImplementedError

        backend = _NoBatch(str(tmp_path / "agent_io" / "t.db"), "quiz")
        backend.initialize()
        echoed = {"review": {"title": "ReviewSchema", "type": "object", "properties": {}}}

        def run():
            backend._gate_schema_echo_records("review", [{"source_guid": "g1", "content": echoed}])

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "Disposition write skipped")

    def test_an_oversized_trace_field_is_kept_off_the_console(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        backend = self._backend(tmp_path)

        def run():
            backend._cap_trace_field("x" * (SQLiteBackend._MAX_TRACE_FIELD_SIZE + 1))

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "Truncating trace field")

    def test_the_trace_marker_does_not_displace_the_workflow_name(self, tmp_path):
        """The one target that already passes extra= must keep its own field."""
        backend = self._backend(tmp_path)

        def run():
            backend.update_prompt_trace_response("score", "r-1", "answer")

        events = [e for e in _warns_from(run, tmp_path) if "No prompt trace row" in e.message]

        assert events, "the no-trace-row warning did not fire"
        assert events[0].diagnostic is True
        assert events[0].data["workflow_name"] == "quiz"

    def test_an_upstream_record_without_content_is_kept_off_the_console(self, tmp_path):
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        class _StubbedUpstream(SQLiteBackend):
            def _get_upstream_actions(self, action_name):
                return ["extract"]

            def _read_target_raw_batch(self, actions, relative_path):
                return {"extract": [{"source_guid": "g1", "content": None}]}

        backend = _StubbedUpstream(str(tmp_path / "agent_io" / "t.db"), "quiz")
        backend.initialize()

        def run():
            backend._reconstruct_from_deltas(
                "review",
                "part.json",
                [{"source_guid": "g1", "_delta_mode": "delta", "content": {}}],
            )

        _assert_kept_off_the_console(_warns_from(run, tmp_path), "has no content")
