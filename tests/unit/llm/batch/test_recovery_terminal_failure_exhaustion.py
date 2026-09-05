"""Both triggers of retry recovery must advance the attempt counter to exhaustion.

A recovery batch stops yielding either by completing with records still
missing or by dying at the provider (FAILED / CANCELLED). Either way the
attempt was spent; a pass that answers by re-reading the parent from scratch
resets ``retry_attempt`` and submits paid batches forever. Passes are driven
the way the workflow re-run loop drives them, and assertions read the
persisted recovery state and the registry, never the pass's return value.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services import retry_ops
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "label_page"
PARENT = "pages.json"
OK_ID = "rec-ok"
MISSING_ID = "rec-missing"

AGENT_CONFIG = {
    "kind": "llm",
    "retry": {"enabled": True, "max_attempts": 2, "on_exhausted": "raise"},
}


class _MetadataBackend:
    """The metadata slice of StorageBackend that registry and state persistence use."""

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
        timestamp="2026-08-30T09:00:00+00:00",
        provider="ollama_local",
        record_count=2,
        file_name=PARENT,
    )


def _registry(backend: _MetadataBackend) -> BatchRegistryManager:
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {PARENT: _parent_entry().to_dict()}
    )
    return BatchRegistryManager(backend, ACTION)


class _Harness:
    """A service over a real registry and real recovery-state persistence.

    The provider reports each entry's own registry status and returns the
    parent's results for the parent id; recovery batch ids yield nothing, which
    is what both a completed-empty and a dead recovery batch deliver.
    """

    def __init__(self) -> None:
        self.backend = _MetadataBackend()
        self.manager = _registry(self.backend)
        self.submitted: list[str] = []
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
            MISSING_ID: {"user_content": "two", "source_guid": MISSING_ID},
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
            [BatchResult(custom_id=OK_ID, content={"topic": "models"}, success=True)]
            if batch_id == "batch_parent"
            else []
        )
        return provider

    def _submit(self, **_kw):
        batch_id = f"batch_retry_{len(self.submitted) + 1}"
        self.submitted.append(batch_id)
        return (batch_id, 1)

    def run_pass(self) -> list[str]:
        def capture_convert(batch_results, **kw):
            self.finalized.append(
                {
                    "batch_results": batch_results,
                    "exhausted_recovery": kw.get("exhausted_recovery"),
                }
            )
            return ([], MagicMock(), None)

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
        """What ``are_all_jobs_completed`` does when the provider reports *status*."""
        assert self.manager.update_status(batch_id, status)

    def state(self):
        return RecoveryStateManager.load(self.backend, ACTION, PARENT)


class TestADeadRecoveryBatchAdvancesTheCounter:
    def test_the_attempt_climbs_instead_of_resetting(self):
        """A pass that sees a FAILED retry batch continues from attempt 1, not from scratch."""
        h = _Harness()
        h.run_pass()
        assert h.submitted == ["batch_retry_1"]
        assert h.state().retry_attempt == 1

        h.mark_recovery("batch_retry_1", BatchStatus.FAILED)
        h.run_pass()

        assert h.state() is not None, "recovery state was finalized instead of continued"
        assert h.state().retry_attempt == 2, (
            "the pass re-read the parent and reset the counter instead of "
            "continuing the recovery it already started"
        )
        assert h.submitted == ["batch_retry_1", "batch_retry_2"]
        assert f"{PARENT}_retry_2" in h.manager.get_all_jobs()

    def test_exhaustion_stops_the_submissions(self):
        """After max_attempts dead batches, the pass finalizes instead of paying again."""
        h = _Harness()
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.FAILED)
        h.run_pass()
        h.mark_recovery("batch_retry_2", BatchStatus.FAILED)
        h.run_pass()

        assert h.submitted == ["batch_retry_1", "batch_retry_2"], (
            "a third provider batch was submitted after max_attempts=2 was spent"
        )
        exhausted = h.finalized[-1]["exhausted_recovery"]
        assert exhausted is not None and MISSING_ID in exhausted
        assert exhausted[MISSING_ID].retry.succeeded is False
        assert h.state() is None, "recovery state must be deleted at finalization"
        assert set(h.manager.get_all_jobs()) == {PARENT}

    def test_a_cancelled_recovery_is_the_same_spent_attempt(self):
        h = _Harness()
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.CANCELLED)
        h.run_pass()

        assert h.state().retry_attempt == 2
        assert h.submitted == ["batch_retry_1", "batch_retry_2"]


class TestACompletedButEmptyRecoveryStillExhausts:
    """The other trigger: the recovery completes with the records still missing."""

    def test_both_triggers_share_one_counter(self):
        h = _Harness()
        h.run_pass()
        h.mark_recovery("batch_retry_1", BatchStatus.COMPLETED)
        h.run_pass()
        assert h.state().retry_attempt == 2

        h.mark_recovery("batch_retry_2", BatchStatus.FAILED)
        h.run_pass()

        assert h.submitted == ["batch_retry_1", "batch_retry_2"]
        exhausted = h.finalized[-1]["exhausted_recovery"]
        assert exhausted is not None and MISSING_ID in exhausted
        assert h.state() is None
