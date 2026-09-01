"""A record the provider answers with an error must be retried like an omitted one.

The batch that produced these results returned two records: one answered, one
answered with a per-record provider error. The errored one carries a real
``custom_id``, so a reconciliation that reads ids alone counts it as received.
Passes are driven the way the workflow re-run loop drives them; assertions read
the persisted recovery state, the registry, and the set handed to finalization.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError, raised_by_exhaustion_policy
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services import retry_ops
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import (
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)

ACTION = "label_page"
PARENT = "pages.json"
OK_ID = "rec-ok"
ERR_ID = "rec-errored"
PROVIDER_ERROR = "rate_limit_exceeded: slow down"

AGENT_CONFIG = {
    "kind": "llm",
    "retry": {"enabled": True, "max_attempts": 2},
}


def _ok(custom_id: str) -> BatchResult:
    return BatchResult(custom_id=custom_id, content={"topic": "models"}, success=True)


def _errored(custom_id: str, error: str = PROVIDER_ERROR) -> BatchResult:
    return BatchResult(custom_id=custom_id, content=None, success=False, error=error)


# ---------------------------------------------------------------------------
# The missing set
# ---------------------------------------------------------------------------


def test_find_missing_ids_counts_a_provider_errored_record_as_missing():
    context_map = {OK_ID: {"user_content": "one"}, ERR_ID: {"user_content": "two"}}

    missing = BatchResultReconciler.find_missing_ids(context_map, [_ok(OK_ID), _errored(ERR_ID)])

    assert missing == {ERR_ID}


def test_find_missing_ids_still_treats_an_answered_record_as_received():
    context_map = {OK_ID: {"user_content": "one"}, ERR_ID: {"user_content": "two"}}

    missing = BatchResultReconciler.find_missing_ids(context_map, [_ok(OK_ID), _ok(ERR_ID)])

    assert missing == set()


# ---------------------------------------------------------------------------
# The merge: a retried record must not end up in the result set twice
# ---------------------------------------------------------------------------


def test_a_successful_retry_supersedes_the_provider_error():
    merged, still_missing, _counts, _ = retry_ops.process_retry_results(
        results=[_ok(ERR_ID)],
        accumulated_results=[_ok(OK_ID), _errored(ERR_ID)],
        context_map={OK_ID: {}, ERR_ID: {}},
        record_failure_counts={ERR_ID: 1},
        missing_ids={ERR_ID},
    )

    for_err = [r for r in merged if r.custom_id == ERR_ID]
    assert len(for_err) == 1, "the superseded provider error is still in the result set"
    assert for_err[0].success is True
    assert still_missing == set()


def test_a_second_provider_error_replaces_the_first_instead_of_stacking():
    merged, still_missing, _counts, _ = retry_ops.process_retry_results(
        results=[_errored(ERR_ID, "server_error: 500")],
        accumulated_results=[_ok(OK_ID), _errored(ERR_ID)],
        context_map={OK_ID: {}, ERR_ID: {}},
        record_failure_counts={ERR_ID: 1},
        missing_ids={ERR_ID},
    )

    for_err = [r for r in merged if r.custom_id == ERR_ID]
    assert len(for_err) == 1
    assert for_err[0].success is False
    assert for_err[0].error == "server_error: 500"
    assert still_missing == {ERR_ID}


# ---------------------------------------------------------------------------
# Live path: parent batch → retry submission → exhaustion
# ---------------------------------------------------------------------------


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


def _parent_entry() -> BatchJobEntry:
    return BatchJobEntry(
        batch_id="batch_parent",
        status=BatchStatus.COMPLETED,
        timestamp="2026-09-01T09:00:00+00:00",
        provider="ollama_local",
        record_count=2,
        file_name=PARENT,
    )


class _Harness:
    """A service over a real registry and real recovery-state persistence.

    The parent batch answers ``OK_ID`` and returns a per-record provider error
    for ``ERR_ID``. Recovery batches return whatever ``recovery_results`` holds.
    """

    def __init__(self, recovery_results: list[BatchResult] | None = None) -> None:
        self.backend = _MetadataBackend()
        self.backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
            {PARENT: _parent_entry().to_dict()}
        )
        self.manager = BatchRegistryManager(self.backend, ACTION)
        self.recovery_results = recovery_results or []
        self.submitted: list[str] = []
        self.submitted_ids: list[set[str]] = []
        self.finalized: list[dict] = []

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=lambda _: self.manager,
            storage_backend=self.backend,
            workflow_name=ACTION,
        )
        service._client_resolver.get_for_batch_id.side_effect = self._resolve
        service._context_manager.load_batch_context_map.return_value = {
            OK_ID: {"user_content": "one", "source_guid": OK_ID},
            ERR_ID: {"user_content": "two", "source_guid": ERR_ID},
        }

        retry_service = MagicMock()
        retry_service.submit_retry_batch.side_effect = self._submit
        retry_service.process_retry_results.side_effect = retry_ops.process_retry_results
        retry_service.build_exhausted_recovery.side_effect = retry_ops.build_exhausted_recovery
        service._retry_service = retry_service

        self.service = service

    def _resolve(self, batch_id, registry_manager, *_a, **_kw):
        entry = registry_manager.get_batch_job_by_id(batch_id)
        if entry is None:
            raise ConfigurationError(f"Cannot determine client for batch_id {batch_id}")
        provider = MagicMock()
        provider.check_status.return_value = entry.status
        provider.retrieve_results.return_value = (
            [_ok(OK_ID), _errored(ERR_ID)]
            if batch_id == "batch_parent"
            else list(self.recovery_results)
        )
        return provider

    def _submit(self, *, missing_ids, **_kw):
        batch_id = f"batch_retry_{len(self.submitted) + 1}"
        self.submitted.append(batch_id)
        self.submitted_ids.append(set(missing_ids))
        return (batch_id, len(missing_ids))

    def run_pass(self):
        def capture_convert(batch_results, **kw):
            self.finalized.append(
                {
                    "batch_results": batch_results,
                    "exhausted_recovery": kw.get("exhausted_recovery"),
                }
            )
            return ([], MagicMock())

        with (
            patch.object(
                self.service,
                "_convert_batch_results_to_workflow_format",
                side_effect=capture_convert,
            ),
            patch.object(self.service, "_write_batch_output"),
        ):
            return self.service.process_all_batch_results("/out", AGENT_CONFIG, action_name=ACTION)

    def mark_recovery(self, batch_id: str, status: BatchStatus) -> None:
        assert self.manager.update_status(batch_id, status)

    def state(self):
        return RecoveryStateManager.load(self.backend, ACTION, PARENT)


class TestTheErroredRecordEntersRecovery:
    def test_the_retry_batch_carries_the_errored_record(self):
        h = _Harness()
        h.run_pass()

        assert h.submitted == ["batch_retry_1"], "no retry batch was submitted"
        assert h.submitted_ids == [{ERR_ID}]

    def test_the_answered_record_is_not_resubmitted(self):
        h = _Harness()
        h.run_pass()

        assert OK_ID not in h.submitted_ids[0]

    def test_recovery_state_records_the_errored_record_as_missing(self):
        h = _Harness()
        h.run_pass()

        state = h.state()
        assert state is not None
        assert state.missing_ids == [ERR_ID]


class TestTheRecoveredRecordIsNotDuplicated:
    def test_a_successful_recovery_leaves_one_answered_row(self):
        h = _Harness(recovery_results=[_ok(ERR_ID)])
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.COMPLETED)
        h.run_pass()

        finalized = h.finalized[-1]["batch_results"]
        for_err = [r for r in finalized if r.custom_id == ERR_ID]
        assert len(for_err) == 1, "finalization received two rows for one record"
        assert for_err[0].success is True
        assert h.state() is None


class TestExhaustionStaysTerminal:
    def test_submissions_stop_at_max_attempts(self):
        h = _Harness(recovery_results=[_errored(ERR_ID)])
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.COMPLETED)
        h.run_pass()
        h.mark_recovery("batch_retry_2", BatchStatus.COMPLETED)
        h.run_pass()

        assert h.submitted == ["batch_retry_1", "batch_retry_2"], (
            "a third provider batch was submitted after max_attempts=2 was spent"
        )
        assert h.state() is None, "recovery state must be deleted at finalization"

    def test_the_provider_error_survives_to_finalization(self):
        h = _Harness(recovery_results=[_errored(ERR_ID, "server_error: 500")])
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.COMPLETED)
        h.run_pass()
        h.mark_recovery("batch_retry_2", BatchStatus.COMPLETED)
        h.run_pass()

        finalized = h.finalized[-1]["batch_results"]
        for_err = [r for r in finalized if r.custom_id == ERR_ID]
        assert len(for_err) == 1
        assert for_err[0].error == "server_error: 500"


# ---------------------------------------------------------------------------
# The terminal row an exhausted, provider-errored record produces
# ---------------------------------------------------------------------------


def _exhausted(custom_id: str) -> dict[str, RecoveryMetadata]:
    return {
        custom_id: RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=2, succeeded=False, reason="missing")
        )
    }


def test_an_exhausted_errored_record_carries_its_retry_history():
    results = BatchResultStrategy().process(
        [_ok(OK_ID), _errored(ERR_ID)],
        context_map={
            OK_ID: {"user_content": "one", "source_guid": OK_ID},
            ERR_ID: {"user_content": "two", "source_guid": ERR_ID},
        },
        agent_config=AGENT_CONFIG,
        exhausted_recovery=_exhausted(ERR_ID),
    )

    for_err = [r for r in results if r.source_guid == ERR_ID]
    assert len(for_err) == 1
    assert for_err[0].status is ProcessingStatus.FAILED
    assert PROVIDER_ERROR in (for_err[0].error or "")
    assert for_err[0].recovery_metadata is not None, (
        "the record spent every retry attempt but its row records none of them"
    )
    assert for_err[0].recovery_metadata.retry.attempts == 2
    assert for_err[0].recovery_metadata.retry.succeeded is False


def test_on_exhausted_raise_halts_on_a_provider_errored_record():
    config = {"kind": "llm", "retry": {"enabled": True, "max_attempts": 2, "on_exhausted": "raise"}}

    with pytest.raises(RuntimeError) as excinfo:
        BatchResultStrategy().process(
            [_errored(ERR_ID)],
            context_map={ERR_ID: {"user_content": "two", "source_guid": ERR_ID}},
            agent_config=config,
            exhausted_recovery=_exhausted(ERR_ID),
        )

    assert raised_by_exhaustion_policy(excinfo.value)


def test_a_failed_record_with_no_retry_history_is_untouched():
    results = BatchResultStrategy().process(
        [_errored(ERR_ID)],
        context_map={ERR_ID: {"user_content": "two", "source_guid": ERR_ID}},
        agent_config=AGENT_CONFIG,
        exhausted_recovery=None,
    )

    for_err = [r for r in results if r.source_guid == ERR_ID]
    assert len(for_err) == 1
    assert for_err[0].status is ProcessingStatus.FAILED
    assert for_err[0].recovery_metadata is None
