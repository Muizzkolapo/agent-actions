"""An all-removed action must look the same to the user in batch and online.

Online reports `SKIP` with `↳ skipped: All records guard-filtered — no output
produced`, and downstream actions cascade-skip.  Batch reported `OK`.

The cause is not the executor but the signal it reads.  A `run_mode: batch` LLM
action never reaches ``CollectionStats.raise_if_terminal_failure`` — the only
writer of the node-level ``skipped`` disposition — because ``pipeline.py`` forks
to ``_handle_batch_mode`` and returns first.  Batch instead recorded a
node-level ``passthrough`` for its empty tombstone, which the classifier does
not recognise.

Uses a real SQLiteBackend: the defect is that the row a mock would fabricate is
never written.
"""

import pytest

from agent_actions.processing.result_collector import write_tombstone_disposition
from agent_actions.storage.backend import (
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.state import ActionStatus

ACTION = "extract_candidates"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="wf")
    b.initialize()
    return b


class TestTheSignalBatchWrites:
    """An empty tombstone means every record was removed and nothing produced."""

    def test_an_empty_tombstone_is_recorded_as_a_skip(self, backend):
        write_tombstone_disposition(backend, ACTION, [], "All records tombstoned")
        assert backend.has_disposition(ACTION, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID)

    def test_a_tombstone_carrying_records_stays_a_passthrough(self, backend):
        """Records that passed through with data were not skipped."""
        write_tombstone_disposition(backend, ACTION, [{"id": 1}], "All records tombstoned")
        assert backend.has_disposition(
            ACTION, DISPOSITION_PASSTHROUGH, record_id=NODE_LEVEL_RECORD_ID
        )
        assert not backend.has_disposition(
            ACTION, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID
        )


class TestTheExecutorClassifiesWhatBatchWrote:
    """The signal must survive into the status the user sees."""

    def _executor_over(self, backend):
        from unittest.mock import MagicMock

        from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies

        deps = MagicMock(spec=ExecutorDependencies)
        deps.action_runner = MagicMock()
        deps.action_runner.storage_backend = backend
        deps.action_runner.execution_order = [ACTION]
        return ActionExecutor(deps)

    def test_an_all_removed_batch_action_resolves_as_skipped(self, backend):
        write_tombstone_disposition(backend, ACTION, [], "All records tombstoned")
        assert self._executor_over(backend)._resolve_completion_status(ACTION) == (
            ActionStatus.SKIPPED
        )

    def test_a_passthrough_with_records_still_completes(self, backend):
        write_tombstone_disposition(backend, ACTION, [{"id": 1}], "All records tombstoned")
        assert self._executor_over(backend)._resolve_completion_status(ACTION) == (
            ActionStatus.COMPLETED
        )


class TestTheBatchResumePathStillRoutesTheAction:
    """The skip signal must not strand the action as a batch failure.

    set_disposition deletes every row for (action, record_id), so the skip
    replaces the passthrough marker the resume path used to key on.
    """

    def _manager_over(self, backend, tmp_path):
        from unittest.mock import MagicMock

        from agent_actions.workflow.managers.batch import BatchLifecycleManager

        m = BatchLifecycleManager.__new__(BatchLifecycleManager)
        m.storage_backend = backend
        m.job_manager = MagicMock()
        return m

    def test_a_skipped_action_is_not_reported_as_a_batch_failure(self, backend, tmp_path):
        write_tombstone_disposition(backend, ACTION, [], "All records tombstoned")
        m = self._manager_over(backend, tmp_path)
        m.job_manager.get_registry_status.return_value = "no_batches"
        _, status = m.handle_batch_agent(ACTION, str(tmp_path))
        assert status != "failed"

    def test_check_batch_submission_still_recognises_the_action(self, backend, tmp_path):
        write_tombstone_disposition(backend, ACTION, [], "All records tombstoned")
        m = self._manager_over(backend, tmp_path)
        assert m.check_batch_submission(ACTION, 0, tmp_path) == "passthrough"
