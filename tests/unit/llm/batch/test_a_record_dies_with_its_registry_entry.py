"""A batch's record dies with the registry entry that names it.

Four places stop naming a batch id — finalising a file, superseding a recovery
round, dropping an unreadable one, and overwriting a failed entry on
resubmission — and a record left by any of them is a payload nothing can reach.

The parent entry is none of these: it survives finalisation and `agac retry`
replays the batch id it still holds.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    RecoveryContext,
)
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

PARENT = "pages.json"
ROUND_1 = f"{PARENT}_{RecoveryType.RETRY}_1"
ACTION = "summarize"


@pytest.fixture
def project(tmp_path):
    """A project root the provider records its batches under."""
    from agent_actions.config.paths import PathManager
    from agent_actions.utils import path_utils

    root = tmp_path / "project"
    root.mkdir()
    (root / "agent_actions.yml").write_text("version: '1.0'\n")

    previous = path_utils._global_path_manager
    path_utils.set_path_manager(PathManager(project_root=root))
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    yield root
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()
    path_utils._global_path_manager = previous


def _submit(batch_id: str) -> None:
    """Record a batch the way a submission does, payload and all."""
    AgacBatchClient._write_state(
        MockBatchState(batch_id=batch_id),
        [{"custom_id": "r1", "user_content": f"content of {batch_id}"}],
    )


def _records(project) -> list[str]:
    state = project / ".agac" / "batch_state"
    return sorted(p.name for p in state.glob("*")) if state.is_dir() else []


def _entry(batch_id, parent=None, attempt=None, status=BatchStatus.COMPLETED) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=batch_id,
        status=status,
        timestamp="t",
        provider="agac-provider",
        file_name=PARENT if parent is None else ROUND_1,
        parent_file_name=parent,
        recovery_type=None if parent is None else RecoveryType.RETRY,
        recovery_attempt=attempt,
    )


class _Registry:
    """Enough of BatchRegistryManager to be saved to, read and removed from."""

    def __init__(self, jobs):
        self._jobs = dict(jobs)

    def get_all_jobs(self):
        return dict(self._jobs)

    def get_batch_job(self, file_name):
        return self._jobs.get(file_name)

    def save_batch_job(self, file_name, entry):
        self._jobs[file_name] = entry

    def remove_batch_job(self, file_name):
        return self._jobs.pop(file_name, None) is not None


def test_releasing_a_batch_takes_its_record_and_its_half_written_tmp(project):
    """`atomic_json_write` mkstemps beside the target, so an interrupted write
    leaves a `.tmp` under a name nothing else looks for, holding the payload."""
    from agent_actions.llm.providers.local_batch_records import release_local_batch_record

    _submit("spent")
    _submit("live")
    orphan = project / ".agac" / "batch_state" / "spent_kj38fa.tmp"
    orphan.write_text('{"tasks": [{"user_content": "content of spent"}]}')

    release_local_batch_record("spent")

    assert _records(project) == ["live.json"]


def test_a_batch_that_was_never_recorded_releases_quietly(project):
    """Every other provider keeps its copy at the vendor, so its batch ids name
    nothing here — releasing one must not be an error."""
    from agent_actions.llm.providers.local_batch_records import release_local_batch_record

    _submit("live")

    release_local_batch_record("batch_abc123_from_openai")

    assert _records(project) == ["live.json"]


def test_a_superseded_round_loses_its_record(project):
    """One live recovery per parent: registering attempt 2 drops attempt 1."""
    for batch_id in ("batch-parent", "batch-retry-1", "batch-retry-2"):
        _submit(batch_id)
    manager = _Registry(
        {PARENT: _entry("batch-parent"), ROUND_1: _entry("batch-retry-1", PARENT, 1)}
    )

    pr.register_recovery_batch(
        manager, ("batch-retry-2", 1), PARENT, "agac-provider", RecoveryType.RETRY, 2
    )

    assert _records(project) == ["batch-parent.json", "batch-retry-2.json"]


def test_an_unreadable_recovery_entry_loses_its_record(project, monkeypatch):
    """Its entry is dropped so the parent goes back to the from-scratch path;
    nothing can be sent back to the round's own batch after that."""
    _submit("batch-parent")
    _submit("batch-retry-1")
    entry = _entry("batch-retry-1", PARENT, 1)
    manager = _Registry({PARENT: _entry("batch-parent"), ROUND_1: entry})
    monkeypatch.setattr(pr.RecoveryStateManager, "load", staticmethod(lambda *a, **k: None))
    service = MagicMock()
    service._resolve_action_name = lambda override=None: ACTION
    service._storage_backend = MagicMock()

    result = pr.process_recovery_batch(
        service, "batch-retry-1", ROUND_1, entry, "/out", {}, manager, ACTION
    )

    assert result is None
    assert _records(project) == ["batch-parent.json"]


def _finalise(project, jobs, finalised):
    """The cleanup that follows a finalised output for PARENT."""
    service = MagicMock()
    service._cleanup_recovery_entries = BatchProcessingService._cleanup_recovery_entries
    manager = _Registry(jobs)
    context = RecoveryContext(
        service=service,
        manager=manager,
        provider=MagicMock(),
        agent_config={},
        output_directory="/out",
        action_name=ACTION,
        start_time=0.0,
    )
    pr.cleanup_recovery(
        context, BatchIdentity(batch_id=finalised, file_name=PARENT, entry=jobs[PARENT])
    )
    return manager


def test_finalising_a_file_loses_the_record_of_the_round_it_drops(project):
    _submit("batch-parent")
    _submit("batch-retry-1")
    jobs = {PARENT: _entry("batch-parent"), ROUND_1: _entry("batch-retry-1", PARENT, 1)}

    _finalise(project, jobs, finalised="batch-retry-1")

    assert _records(project) == ["batch-parent.json"]


def test_finalising_a_file_keeps_the_parent_whose_entry_survives(project):
    """`agac retry` replays the batch id a COMPLETED parent entry still names."""
    _submit("batch-parent")
    jobs = {PARENT: _entry("batch-parent")}

    manager = _finalise(project, jobs, finalised="batch-parent")

    assert PARENT in manager.get_all_jobs()
    assert _records(project) == ["batch-parent.json"]


def test_a_resubmission_over_a_failed_batch_loses_the_failed_record(tmp_path, project):
    """A FAILED entry does not block resubmission — it is overwritten, and the
    batch it named stops being reachable at that moment."""
    _submit("batch-failed")
    service = BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        registry_manager_factory=MagicMock(),
    )
    prepared = MagicMock(
        tasks=[{"target_id": "r1", "content": "x", "prompt": "p"}],
        context_map={},
        task_count=1,
        stats=MagicMock(total_filtered=0, total_skipped=0),
    )
    service._task_preparator.prepare_tasks.return_value = prepared
    service._client_resolver.get_for_config.return_value = MagicMock(
        submit_batch=MagicMock(return_value=("batch-new", BatchStatus.SUBMITTED))
    )
    registry = _Registry({"my_action": _entry("batch-failed", status=BatchStatus.FAILED)})
    service._registry_manager_factory = lambda _name: registry

    service.submit_batch_job(
        agent_config={"model_vendor": "agac-provider"},
        batch_name="my_action",
        data=[{"id": 1}],
        output_directory=str(tmp_path),
    )

    assert registry.get_batch_job("my_action").batch_id == "batch-new"
    assert _records(project) == []
