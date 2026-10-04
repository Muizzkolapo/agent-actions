"""An action waits for a finished file its collect pass could not read.

Driven through the real lifecycle manager, job manager, registry and collect pass over a
SQLite store. Only the provider is fake, and finalizing a file is reduced to the stamp
finalize writes, which is all the decision to complete reads of it; a file a test names in
``read_through`` is read for real.

Every entry starts out finished, as a run finds them once an earlier run's poll has
recorded that: the collect pass's own status check is then the only call to the
provider, and the one that can fail.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
    ContextMetaKeys,
    FilterStatus,
    RecoveryType,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.batch import BatchLifecycleManager

ACTION = "summarize"
PAGES = ("page1.json", "page2.json", "page3.json")


class _Provider:
    """Says what the registry says of each batch, and cannot be reached about ``unreachable``."""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.unreachable: set[str] = set()

    def check_status(self, batch_id: str) -> str:
        if batch_id in self.unreachable:
            raise ConnectionError("the provider could not be reached")
        return self.statuses[batch_id]


class _Resolver:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_for_batch_id(self, *args, **kwargs) -> _Provider:
        return self.provider


class _Action:
    def __init__(
        self,
        tmp_path: Path,
        collected: tuple[str, ...] = (),
        statuses: dict[str, str] | None = None,
    ) -> None:
        statuses = {name: (statuses or {}).get(name, BatchStatus.COMPLETED) for name in PAGES}
        self.out = str(tmp_path / "target" / ACTION)
        self.backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        self.backend.initialize()
        self.backend.save_metadata(
            f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}",
            json.dumps(
                {
                    name: BatchJobEntry(
                        batch_id=f"batch-{name}",
                        status=status,
                        timestamp="2026-10-04T09:00:00+00:00",
                        provider="agac-provider",
                        record_count=2,
                        file_name=name,
                        collected_at="2026-10-04T09:05:00+00:00" if name in collected else None,
                    ).to_dict()
                    for name, status in statuses.items()
                }
            ),
        )
        self.provider = _Provider({f"batch-{name}": s for name, s in statuses.items()})
        resolver = _Resolver(self.provider)
        self.finalized: list[str] = []
        self.broken: set[str] = set()
        self.read_through: set[str] = set()
        service = BatchProcessingService(
            client_resolver=resolver,
            context_manager=BatchContextManager(),
            result_processor=None,
            registry_manager_factory=lambda name: BatchRegistryManager(self.backend, name),
            storage_backend=self.backend,
            workflow_name=ACTION,
        )
        self._read = service._process_single_batch_file
        service._process_single_batch_file = self._finalize
        self.lifecycle = BatchLifecycleManager(
            BatchJobManager(client_resolver=resolver, storage_backend=self.backend),
            service,
            storage_backend=self.backend,
        )

    def _finalize(self, *, file_name: str, manager: BatchRegistryManager, **kwargs) -> str | None:
        if file_name in self.read_through:
            return self._read(file_name=file_name, manager=manager, **kwargs)
        if file_name in self.broken:
            raise ValueError(f"{file_name} cannot be read")
        self.finalized.append(file_name)
        manager.mark_collected(file_name)
        return f"{self.out}/{file_name}"

    def register(self, entry: BatchJobEntry) -> None:
        BatchRegistryManager(self.backend, ACTION).save_batch_job(entry.file_name, entry)
        self.provider.statuses[entry.batch_id] = entry.status

    def send(self, file_name: str, *record_ids: str) -> None:
        """Record what the file's batch was sent, which is where its records are found."""
        BatchContextManager.save_batch_context_map(
            self.backend,
            ACTION,
            {
                record_id: {
                    "source_guid": record_id,
                    ContextMetaKeys.FILTER_STATUS: str(FilterStatus.INCLUDED),
                }
                for record_id in record_ids
            },
            file_name,
        )

    def dispositions(self) -> dict[str, str]:
        return {
            row["record_id"]: row["disposition"] for row in self.backend.get_disposition(ACTION)
        }

    def cannot_reach(self, *names: str) -> None:
        self.provider.unreachable = {f"batch-{name}" for name in names}

    def check(self) -> tuple[str | None, str]:
        return self.lifecycle.handle_batch_agent(ACTION, self.out, {})


def _retry_of(parent: str) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=f"batch-{parent}_retry_1",
        status=BatchStatus.COMPLETED,
        timestamp="2026-10-04T09:10:00+00:00",
        provider="agac-provider",
        record_count=1,
        file_name=f"{parent}_retry_1",
        parent_file_name=parent,
        recovery_type=RecoveryType.RETRY,
        recovery_attempt=1,
    )


def test_an_action_does_not_complete_past_a_finished_file_it_could_not_read(tmp_path):
    """Completed, the action is not run again, and nothing reads those batches afterwards."""
    action = _Action(tmp_path)
    action.cannot_reach("page2.json", "page3.json")

    assert action.check() == (None, "in_progress")
    assert action.finalized == ["page1.json"]


def test_the_run_after_it_reads_those_files_and_completes(tmp_path):
    action = _Action(tmp_path)
    action.cannot_reach("page2.json", "page3.json")
    action.check()
    action.cannot_reach()

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page2.json", "page3.json"]


def test_the_run_names_each_file_it_could_not_read(tmp_path, caplog):
    action = _Action(tmp_path)
    action.cannot_reach("page2.json", "page3.json")

    with caplog.at_level(logging.WARNING, logger="agent_actions.llm.batch.services.processing"):
        action.check()

    assert "Could not read page2.json" in caplog.text
    assert "Could not read page3.json" in caplog.text


def test_a_pass_that_could_read_no_file_waits_rather_than_failing(tmp_path):
    """A provider out of reach is a reason to come back, as it is while a batch is out."""
    action = _Action(tmp_path)
    action.cannot_reach(*PAGES)

    assert action.check() == (None, "in_progress")
    assert action.finalized == []


@pytest.mark.parametrize(
    ("collected", "unread"),
    [
        (("page1.json", "page2.json"), ("page3.json",)),
        (("page1.json",), ("page2.json", "page3.json")),
    ],
)
def test_files_collected_before_do_not_stand_in_for_one_left_unread(tmp_path, collected, unread):
    """The pass writes nothing and is not an error, which the action must not read as done."""
    action = _Action(tmp_path, collected=collected)
    action.cannot_reach(*unread)

    assert action.check() == (None, "in_progress")
    assert action.finalized == []


def test_the_records_of_a_file_left_unread_are_not_reported_as_orphans(tmp_path, caplog):
    """They are waited for; the warning tells the user they were left behind."""
    action = _Action(tmp_path)
    action.backend.set_disposition(ACTION, "page2-a", DISPOSITION_DEFERRED)
    action.cannot_reach("page2.json")

    with caplog.at_level(logging.WARNING, logger="agent_actions.workflow.managers.batch"):
        action.check()

    assert "orphan" not in caplog.text


def test_a_file_whose_reading_failed_does_not_hold_the_action(tmp_path):
    """Its records are marked failed, which is what `agac retry` finds. Waited for, a file
    that fails the same way every time would hold the action for good."""
    action = _Action(tmp_path)
    action.broken = {"page2.json"}

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page3.json"]


@pytest.mark.parametrize("ended", [BatchStatus.FAILED, BatchStatus.CANCELLED])
def test_a_batch_that_ended_without_results_is_not_left_unread(tmp_path, ended):
    """There are no results to wait for: waiting on it would hold the action for good."""
    action = _Action(tmp_path, statuses={"page3.json": ended})

    collected = action.lifecycle.processing_service.process_all_batch_results(
        action.out, {}, action_name=ACTION
    )

    assert (collected.written, collected.unread) == (
        [f"{action.out}/page1.json", f"{action.out}/page2.json"],
        [],
    )


def test_a_finished_batch_the_provider_reports_running_again_is_waited_for(tmp_path):
    """Its records are not failed: `agac retry` would send them again while the provider
    may still answer them."""
    action = _Action(tmp_path)
    action.send("page2.json", "page2-a")
    action.provider.statuses["batch-page2.json"] = BatchStatus.IN_PROGRESS

    assert action.check() == (None, "in_progress")
    assert action.finalized == ["page1.json", "page3.json"]
    assert action.dispositions() == {}


@pytest.mark.parametrize("answer", [BatchStatus.FAILED, "expired", "unknown"])
def test_a_finished_batch_the_provider_no_longer_reports_finished_fails_its_records(
    tmp_path, answer
):
    """No later pass can read it, so waiting on it would hold the action for good. Its
    records are marked failed instead, which is what `agac retry` finds."""
    action = _Action(tmp_path)
    action.send("page2.json", "page2-a", "page2-b")
    action.provider.statuses["batch-page2.json"] = answer

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page3.json"]
    assert action.dispositions() == {"page2-a": DISPOSITION_FAILED, "page2-b": DISPOSITION_FAILED}


def test_a_recovery_round_the_provider_does_not_know_fails_the_records_of_its_file(tmp_path):
    """A round is sent from its file's context map, and registered under a name of its own
    that has none."""
    action = _Action(tmp_path)
    action.send("page3.json", "page3-a", "page3-b")
    action.register(_retry_of("page3.json"))
    action.provider.statuses["batch-page3.json_retry_1"] = "unknown"

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page2.json"]
    assert action.dispositions() == {"page3-a": DISPOSITION_FAILED, "page3-b": DISPOSITION_FAILED}


def test_a_file_handed_back_by_a_recovery_dropped_in_the_pass_is_waited_for(tmp_path):
    """The recovery superseded the file for the whole pass, which skipped it; dropped for
    want of a recovery state, it hands the file back to be read from scratch. Completed,
    the action would never read it."""
    action = _Action(tmp_path)
    action.register(_retry_of("page3.json"))
    action.read_through = {"page3.json_retry_1"}

    assert action.check() == (None, "in_progress")
    assert action.finalized == ["page1.json", "page2.json"]

    assert action.check() == (action.out, "completed")
    assert action.finalized == ["page1.json", "page2.json", "page3.json"]
