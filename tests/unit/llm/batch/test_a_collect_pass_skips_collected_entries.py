"""A collect pass finalizes only the entries whose results are still owed.

Driven over a real registry. The stamp is what ``finalize_batch_output`` writes once a
file's results are stored, so an entry carrying it has nothing left to give: read again,
its spent batch would be written over whatever a later run stored for the file.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.processing import BatchProcessingService

ACTION = "label_page"


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value


def _service(entries: dict[str, str | None]):
    """A service over a registry holding one completed entry per file: name -> collected_at."""
    backend = _MetadataBackend()
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {
            name: BatchJobEntry(
                batch_id=f"batch-{name}",
                status=BatchStatus.COMPLETED,
                timestamp="2026-10-04T09:00:00+00:00",
                provider="openai",
                record_count=1,
                file_name=name,
                collected_at=collected_at,
            ).to_dict()
            for name, collected_at in entries.items()
        }
    )
    manager = BatchRegistryManager(backend, ACTION)
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda _: manager,
        storage_backend=backend,
        workflow_name=ACTION,
    )
    service._provider_status = MagicMock(return_value=BatchStatus.COMPLETED)
    service._process_single_batch_file = MagicMock(
        side_effect=lambda **kw: f"/out/{kw['file_name']}"
    )
    return service


def _finalized(service) -> list[str]:
    return [call.kwargs["file_name"] for call in service._process_single_batch_file.call_args_list]


def _polled(service) -> list[str]:
    return [call.args[0] for call in service._provider_status.call_args_list]


def test_an_entry_already_collected_is_neither_polled_nor_finalized():
    service = _service({"page1.json": "2026-10-04T09:05:00+00:00", "page2.json": None})

    written = service.process_all_batch_results("/out", action_name=ACTION).written

    assert _finalized(service) == ["page2.json"]
    assert _polled(service) == ["batch-page2.json"]
    assert written == ["/out/page2.json"]


def test_a_pass_over_entries_that_are_all_collected_writes_nothing_and_is_not_an_error():
    service = _service({"page1.json": "2026-10-04T09:05:00+00:00"})

    assert service.process_all_batch_results("/out", action_name=ACTION).written == []
    assert _finalized(service) == []


def test_an_entry_from_before_the_stamp_is_still_collected():
    """It cannot be told from one whose results are owed, and dropping owed results
    strands the batch; written once more is the safe direction."""
    service = _service({"page1.json": None})

    service.process_all_batch_results("/out", action_name=ACTION)

    assert _finalized(service) == ["page1.json"]


def test_a_skipped_collected_entry_keeps_a_pass_that_wrote_nothing_from_failing():
    """As a replay of the collected file that succeeded did. The entry still owed beside it
    is handed back unread, for the action to wait on: not failed, and not passed over."""
    service = _service({"page1.json": "2026-10-04T09:05:00+00:00", "page2.json": None})
    service._provider_status.return_value = None

    collected = service.process_all_batch_results("/out", action_name=ACTION)

    assert (collected.written, collected.unread) == ([], ["page2.json"])
    assert _finalized(service) == []
