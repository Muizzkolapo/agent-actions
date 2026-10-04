"""An action waits for a finished file its collect pass could not read.

Driven through the real lifecycle manager, job manager, registry and collect pass over a
SQLite store. Only the provider is fake, and finalizing a file is reduced to the stamp
finalize writes, which is all the decision to complete reads of it.

Every entry starts out finished, as a run finds them once an earlier run's poll has
recorded that: the collect pass's own status check is then the only call to the
provider, and the one that can fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.batch import BatchLifecycleManager

ACTION = "summarize"
PAGES = ("page1.json", "page2.json", "page3.json")


class _Provider:
    """Has finished every batch, and cannot be reached about the ones in ``unreachable``."""

    def __init__(self) -> None:
        self.unreachable: set[str] = set()

    def check_status(self, batch_id: str) -> str:
        if batch_id in self.unreachable:
            raise ConnectionError("the provider could not be reached")
        return BatchStatus.COMPLETED


class _Resolver:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    def get_for_batch_id(self, *args, **kwargs) -> _Provider:
        return self.provider


class _Action:
    def __init__(self, tmp_path: Path, collected: tuple[str, ...] = ()) -> None:
        self.out = str(tmp_path / "target" / ACTION)
        self.backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        self.backend.initialize()
        self.backend.save_metadata(
            f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}",
            json.dumps(
                {
                    name: BatchJobEntry(
                        batch_id=f"batch-{name}",
                        status=BatchStatus.COMPLETED,
                        timestamp="2026-10-04T09:00:00+00:00",
                        provider="agac-provider",
                        record_count=2,
                        file_name=name,
                        collected_at="2026-10-04T09:05:00+00:00" if name in collected else None,
                    ).to_dict()
                    for name in PAGES
                }
            ),
        )
        self.provider = _Provider()
        resolver = _Resolver(self.provider)
        self.finalized: list[str] = []
        service = BatchProcessingService(
            client_resolver=resolver,
            context_manager=None,
            result_processor=None,
            registry_manager_factory=lambda name: BatchRegistryManager(self.backend, name),
            storage_backend=self.backend,
            workflow_name=ACTION,
        )
        service._process_single_batch_file = self._finalize
        self.lifecycle = BatchLifecycleManager(
            BatchJobManager(client_resolver=resolver, storage_backend=self.backend),
            service,
            storage_backend=self.backend,
        )

    def _finalize(self, *, file_name: str, manager: BatchRegistryManager, **_kwargs) -> str:
        self.finalized.append(file_name)
        manager.mark_collected(file_name)
        return f"{self.out}/{file_name}"

    def cannot_reach(self, *names: str) -> None:
        self.provider.unreachable = {f"batch-{name}" for name in names}

    def check(self) -> tuple[str | None, str]:
        return self.lifecycle.handle_batch_agent(ACTION, self.out, {})


def test_an_action_does_not_complete_past_a_finished_file_it_could_not_read(tmp_path):
    """Completed, the action is not run again, and nothing reads those batches afterwards."""
    action = _Action(tmp_path)
    action.cannot_reach("page2.json", "page3.json")

    assert action.check() == (None, "in_progress")
    assert action.finalized == ["page1.json"]


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
