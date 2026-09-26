"""The entry that survives a finalisation carries the collected stamp.

`has_uncollected_jobs` reads a stamp rather than the COMPLETED status, because a
provider poll writes that status the moment a batch finishes and long before
anything is retrieved. A reader is only worth as much as its writer: these drive
the real finalisation over a real registry and assert the stamp landed, so an
implementation that never writes one — which would pause every batch action
forever — cannot pass.

The recovery case is the one that is easy to get wrong. A round finalises under
its own batch id and the cleanup that follows deletes that entry, so a stamp
placed on the round is thrown away with it and the parent, which is what
survives, still reads as never collected.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services import retry_ops
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "label_page"
PARENT = "pages.json"
OK_ID = "rec-ok"
MISSING_ID = "rec-missing"

NO_RECOVERY = {"kind": "llm", "retry": {"enabled": False}}
WITH_RETRY = {"kind": "llm", "retry": {"enabled": True, "max_attempts": 1}}


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


def _harness(agent_config):
    backend = _MetadataBackend()
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {
            PARENT: BatchJobEntry(
                batch_id="batch_parent",
                status=BatchStatus.COMPLETED,
                timestamp="2026-08-30T09:00:00+00:00",
                provider="ollama_local",
                record_count=2,
                file_name=PARENT,
            ).to_dict()
        }
    )
    manager = BatchRegistryManager(backend, ACTION)

    def resolve(batch_id, registry_manager, *_a, **_kw):
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

    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda _: manager,
        storage_backend=backend,
        workflow_name=ACTION,
    )
    service._client_resolver.get_for_batch_id.side_effect = resolve
    service._context_manager.load_batch_context_map.return_value = {
        OK_ID: {"user_content": "one", "source_guid": OK_ID},
        MISSING_ID: {"user_content": "two", "source_guid": MISSING_ID},
    }

    submitted: list[str] = []

    def submit(**_kw):
        batch_id = f"batch_retry_{len(submitted) + 1}"
        submitted.append(batch_id)
        return (batch_id, 1)

    retry_service = MagicMock()
    retry_service.submit_retry_batch.side_effect = submit
    retry_service.process_retry_results.side_effect = retry_ops.process_retry_results
    retry_service.build_exhausted_recovery.side_effect = retry_ops.build_exhausted_recovery
    service._retry_service = retry_service

    def run_pass():
        with (
            patch.object(
                service,
                "_convert_batch_results_to_workflow_format",
                side_effect=lambda batch_results, **kw: ([], MagicMock(), None),
            ),
            patch.object(service, "_write_batch_output"),
        ):
            return service.process_all_batch_results("/out", agent_config, action_name=ACTION)

    return manager, run_pass, submitted


def test_finalising_a_batch_stamps_the_entry_it_wrote():
    manager, run_pass, _ = _harness(NO_RECOVERY)
    assert manager.has_uncollected_jobs(), "the fixture started already collected"

    run_pass()

    assert manager.get_batch_job(PARENT).collected_at is not None
    assert not manager.has_uncollected_jobs()


def test_finalising_a_recovery_round_stamps_the_parent_that_survives_it():
    """The round's own entry is deleted by the cleanup that follows finalisation,
    so a stamp placed there is lost and the parent reads as never collected —
    leaving the action asking to be run again for results it already has."""
    manager, run_pass, submitted = _harness(WITH_RETRY)

    run_pass()
    assert submitted, "the fixture did not reach a retry round"
    assert manager.has_uncollected_jobs(), "nothing is collected while a round is in flight"

    manager.update_status(submitted[0], BatchStatus.FAILED)
    run_pass()

    surviving = manager.get_all_jobs()
    assert PARENT in surviving, "the parent is the entry that survives a recovery"
    assert surviving[PARENT].collected_at is not None, (
        "the parent was never stamped, so the action still reports a pause"
    )
    assert not manager.has_uncollected_jobs()
