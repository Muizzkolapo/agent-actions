"""Which errors stop a batch collect pass, and which fail only the file they came from.

Fatality is declared where an error is raised (`mark_action_fatal`), never read from its
type. A bare RuntimeError that a provider's SDK raises while one file is read fails that
file's records, which `agac retry` sends again. An `expect:` block that cannot be resolved
fails every file the same way, so it stops the pass.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import (
    ConfigurationError,
    ProcessingError,
    is_action_fatal,
    mark_action_fatal,
)
from agent_actions.expectations.service import (
    ExpectationConfigurationError,
    create_expectation_service_from_config,
)
from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
    FilterStatus,
    UnknownRecoveryState,
)
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage.backend import DISPOSITION_FAILED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

FILES = ["a.json", "b.json"]


def _entry(name: str) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=f"b_{name}",
        status=BatchStatus.COMPLETED,
        timestamp="t",
        provider="mock",
        file_name=name,
    )


def _service(storage_backend=None) -> tuple[BatchProcessingService, MagicMock]:
    entries = {name: _entry(name) for name in FILES}
    manager = MagicMock()
    manager.get_all_jobs.return_value = entries
    manager.get_batch_job.side_effect = entries.get
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda name: manager,
        workflow_name="act",
        storage_backend=storage_backend,
    )
    service._provider_status = MagicMock(return_value=BatchStatus.COMPLETED)
    return service, manager


def _first_file_raises(service: BatchProcessingService, raise_it) -> list[str]:
    """Have a.json's processing call *raise_it* and b.json's succeed; return what was visited."""
    visited: list[str] = []

    def process(*, file_name, **_kwargs):
        visited.append(file_name)
        if file_name == "a.json":
            raise_it()
        return f"/out/{file_name}"

    service._process_single_batch_file = process
    return visited


def _raising(error: Exception):
    def raise_it():
        raise error

    return raise_it


class TestAnErrorConfinedToOneFileFailsOnlyThatFile:
    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(RuntimeError("the SDK's connection pool is closed"), id="sdk-runtime"),
            pytest.param(
                ConfigurationError("Cannot determine client for batch_id b_a.json"),
                id="configuration",
            ),
        ],
    )
    def test_the_pass_goes_on_and_the_file_records_fail(self, error):
        service, _ = _service()
        service._fail_abandoned_records = MagicMock(return_value=True)
        visited = _first_file_raises(service, _raising(error))

        collected = service.process_all_batch_results("/out", {}, "act")

        assert visited == FILES
        assert collected.written == ["/out/b.json"]
        service._fail_abandoned_records.assert_called_once()
        call = service._fail_abandoned_records.call_args.kwargs
        assert (call["file_name"], call["error"]) == ("a.json", error)


def _a_bare_expect_block_with_no_schema():
    create_expectation_service_from_config({}, action_name="act", agent_config={})


def _a_bare_expect_block_under_repair_none_whose_schema_has_no_rules():
    create_expectation_service_from_config(
        {"repair": "none"},
        action_name="act",
        agent_config={"schema": {"fields": [{"id": "options", "type": "array"}]}},
    )


def _a_schema_whose_rules_have_the_wrong_shape():
    create_expectation_service_from_config(
        {"repair": "none"},
        action_name="act",
        agent_config={
            "schema": {"fields": [{"id": "options", "type": "array"}], "expectations": "x"}
        },
    )


def _a_suite_with_no_project_root():
    create_expectation_service_from_config(
        {"suite": "shared", "repair": "none"}, action_name="act", agent_config={}
    )


def _a_suite_that_cannot_be_loaded(tmp_path: Path):
    create_expectation_service_from_config(
        {"suite": "absent", "repair": "none"},
        action_name="act",
        agent_config={"_project_root": str(tmp_path)},
    )


def _a_recovery_state_of_an_unknown_phase():
    RecoveryState(phase="made_up")


def _a_registry_entry_of_an_unknown_recovery_type():
    BatchJobEntry.from_dict(
        {
            "batch_id": "b",
            "status": "completed",
            "timestamp": "t",
            "provider": "mock",
            "recovery_type": "made_up",
        }
    )


def _a_registry_whose_cache_cannot_be_loaded():
    manager = BatchRegistryManager(MagicMock(), "act")
    with patch.object(manager, "_load_registry", return_value=None):
        manager.mark_collected("a.json")


def _a_store_that_is_not_open(tmp_path: Path):
    SQLiteBackend(str(tmp_path / "wf.db"), "wf").connection  # noqa: B018 - the access raises


RAISE_SITES = pytest.mark.parametrize(
    ("raise_site", "error_type"),
    [
        pytest.param(_a_bare_expect_block_with_no_schema, ExpectationConfigurationError),
        pytest.param(
            _a_bare_expect_block_under_repair_none_whose_schema_has_no_rules,
            ExpectationConfigurationError,
        ),
        pytest.param(_a_schema_whose_rules_have_the_wrong_shape, ExpectationConfigurationError),
        pytest.param(_a_suite_with_no_project_root, ExpectationConfigurationError),
        pytest.param(_a_suite_that_cannot_be_loaded, ExpectationConfigurationError),
        pytest.param(_a_recovery_state_of_an_unknown_phase, UnknownRecoveryState),
        pytest.param(_a_registry_entry_of_an_unknown_recovery_type, UnknownRecoveryState),
        pytest.param(_a_registry_whose_cache_cannot_be_loaded, RuntimeError),
        pytest.param(_a_store_that_is_not_open, RuntimeError),
    ],
)


def _call(raise_site, tmp_path: Path) -> None:
    if raise_site in (_a_suite_that_cannot_be_loaded, _a_store_that_is_not_open):
        raise_site(tmp_path)
    else:
        raise_site()


class TestAnErrorDeclaredFatalWhereItIsRaisedStopsThePass:
    @RAISE_SITES
    def test_the_raise_site_declares_it(self, raise_site, error_type, tmp_path):
        with pytest.raises(error_type) as raised:
            _call(raise_site, tmp_path)

        assert is_action_fatal(raised.value)

    @RAISE_SITES
    def test_the_pass_stops_at_the_file_that_raised_it(self, raise_site, error_type, tmp_path):
        service, _ = _service()
        service._fail_abandoned_records = MagicMock(return_value=True)
        visited = _first_file_raises(service, lambda: _call(raise_site, tmp_path))

        with pytest.raises(error_type):
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json"]
        service._fail_abandoned_records.assert_not_called()

    def test_an_unknown_entry_the_registry_refuses_to_load_stays_declared(self):
        """The registry raises its own refusal, naming the action, from the entry's."""
        backend = MagicMock()
        backend.load_metadata.return_value = (
            '{"x": {"batch_id": "b", "status": "completed", "timestamp": "t", '
            '"provider": "mock", "recovery_type": "made_up"}}'
        )

        with pytest.raises(UnknownRecoveryState) as raised:
            BatchRegistryManager(backend, "act").get_all_jobs()

        assert is_action_fatal(raised.value)


class TestAnExpectBlockThatCannotBeResolvedStopsThePass:
    """Driven through the real per-file processing, down to where the suite is loaded."""

    def test_a_suite_that_cannot_be_loaded_stops_the_pass_at_the_first_file(self, tmp_path):
        store = SQLiteBackend(str(tmp_path / "wf.db"), "wf")
        store.initialize()
        service, _ = _service(storage_backend=store)
        service._result_processor = BatchResultStrategy()
        service._fail_abandoned_records = MagicMock(return_value=True)
        service._context_manager.load_batch_context_map.return_value = {}
        config = {
            "model_vendor": "mock",
            "model_name": "m",
            "expect": {"suite": "absent", "repair": "none"},
            "_project_root": str(tmp_path),
        }
        processed: list[str] = []
        process = service._process_single_batch_file

        def counted(**kwargs):
            processed.append(kwargs["file_name"])
            return process(**kwargs)

        service._process_single_batch_file = counted

        try:
            with (
                patch(
                    "agent_actions.llm.batch.services.processing.retrieve_and_reconcile",
                    return_value=[],
                ),
                pytest.raises(ExpectationConfigurationError, match="absent"),
            ):
                service.process_all_batch_results(str(tmp_path / "out"), config, "act")
        finally:
            store.close()

        assert processed == ["a.json"]
        service._fail_abandoned_records.assert_not_called()


def _included(source_guid: str) -> dict:
    record: dict = {"source_guid": source_guid}
    BatchContextMetadata.set_filter_status(record, FilterStatus.INCLUDED)
    return record


class TestRecordsThatCannotBeMarkedFailedFailTheAction:
    """A file whose reading failed has its records marked failed from its context map.
    When that map cannot be read either, its records would keep the `deferred` their
    submission stamped, and the action would read complete over them."""

    def test_the_action_fails_once_the_pass_has_read_the_other_files(self):
        backend = MagicMock()
        service, _ = _service(storage_backend=backend)

        def load(_backend, _action, file_name):
            if file_name == "a.json":
                raise ProcessingError("Failed to load context map: disk I/O error")
            return {"t1": _included("sg-b")}

        service._context_manager.load_batch_context_map.side_effect = load
        visited = _first_file_raises(service, _raising(ValueError("the answer is not JSON")))

        with pytest.raises(ProcessingError) as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert visited == FILES
        assert is_action_fatal(raised.value)
        message = str(raised.value)
        assert "a.json" in message
        assert "the answer is not JSON" in message
        assert "deferred" in message
        backend.set_disposition.assert_not_called()

    def test_records_marked_failed_do_not_fail_the_action(self):
        backend = MagicMock()
        service, _ = _service(storage_backend=backend)
        service._context_manager.load_batch_context_map.return_value = {"t1": _included("sg-a")}
        _first_file_raises(service, _raising(ValueError("the answer is not JSON")))

        collected = service.process_all_batch_results("/out", {}, "act")

        assert collected.written == ["/out/b.json"]
        ((args, kwargs),) = [
            (c.args, c.kwargs)
            for c in backend.set_disposition.call_args_list
            if DISPOSITION_FAILED in c.args
        ]
        assert args[1] == "sg-a"
        assert "the answer is not JSON" in kwargs["reason"]

    def test_with_no_store_nothing_waits_and_the_pass_goes_on(self):
        service, _ = _service(storage_backend=None)
        _first_file_raises(service, _raising(ValueError("the answer is not JSON")))

        collected = service.process_all_batch_results("/out", {}, "act")

        assert collected.written == ["/out/b.json"]

    def test_a_parked_halt_is_raised_first(self):
        from agent_actions.errors.base import exhaustion_halt

        backend = MagicMock()
        service, _ = _service(storage_backend=backend)
        service._context_manager.load_batch_context_map.side_effect = ProcessingError("gone")
        halt = exhaustion_halt("Retry exhausted for r1 (on_exhausted=raise)")
        visited: list[str] = []

        def process(*, file_name, **_kwargs):
            visited.append(file_name)
            raise halt if file_name == "a.json" else ValueError("the answer is not JSON")

        service._process_single_batch_file = process

        with pytest.raises(RuntimeError) as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert raised.value is halt
        assert visited == FILES


def test_mark_action_fatal_is_what_the_loop_reads():
    """A guard for the probes: the loop reads the declaration, whatever the type."""
    service, _ = _service()
    service._fail_abandoned_records = MagicMock(return_value=True)
    visited = _first_file_raises(service, _raising(mark_action_fatal(KeyError("k"))))

    with pytest.raises(KeyError):
        service.process_all_batch_results("/out", {}, "act")

    assert visited == ["a.json"]
