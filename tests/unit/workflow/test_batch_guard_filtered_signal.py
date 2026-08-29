"""An all-removed action must look the same to the user in batch and online.

Online reports SKIP with "All records guard-filtered — no output produced" and
downstream actions cascade-skip.  Batch reported OK.

The executor is not the cause; the signal it reads is.  A ``run_mode: batch``
LLM action never reaches ``CollectionStats.raise_if_terminal_failure`` — the
only writer of the node-level ``skipped`` disposition — because
``workflow/pipeline.py`` forks to ``_handle_batch_mode`` and returns first.
Batch records a node-level ``passthrough`` for its empty tombstone instead.

That row cannot simply be swapped for ``skipped``: ``set_disposition`` deletes
every row for ``(action, record_id)``, so it is the batch resume path's only
marker, and ``_has_blocking_disposition`` clears a node-level ``skipped`` as
stale whenever target files exist — which they do, since batch writes an empty
chunk file.  So the classifier learns to read what batch writes.

Real SQLiteBackend throughout: the defect is that the row a mock would
fabricate is never written.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.processing.result_collector import write_node_level_disposition
from agent_actions.storage.backend import DISPOSITION_PASSTHROUGH
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStatus

ACTION = "extract_candidates"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="wf")
    b.initialize()
    return b


def _executor(backend, record_count):
    deps = MagicMock(spec=ExecutorDependencies)
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [ACTION]
    ex = ActionExecutor(deps)
    ex._count_records_for_action = MagicMock(return_value=record_count)
    return ex


def _batch_wrote_an_empty_tombstone(backend):
    """Exactly what workflow/pipeline.py records for an all-filtered batch action."""
    write_node_level_disposition(backend, ACTION, DISPOSITION_PASSTHROUGH, "All records tombstoned")


class TestBatchsAllRemovedSignalIsClassifiedAsASkip:
    def test_a_passthrough_that_produced_nothing_is_a_skip(self, backend):
        _batch_wrote_an_empty_tombstone(backend)
        assert _executor(backend, 0)._resolve_completion_status(ACTION) == (ActionStatus.SKIPPED)

    def test_the_resume_marker_is_left_intact(self, backend):
        """The classifier must read the row, never consume it."""
        _batch_wrote_an_empty_tombstone(backend)
        _executor(backend, 0)._resolve_completion_status(ACTION)
        assert backend.has_disposition(ACTION, DISPOSITION_PASSTHROUGH)


class TestNothingElseBecomesASkip:
    def test_a_passthrough_that_produced_records_still_completes(self, backend):
        """Records that genuinely passed through are not a skip."""
        _batch_wrote_an_empty_tombstone(backend)
        assert _executor(backend, 7)._resolve_completion_status(ACTION) == (ActionStatus.COMPLETED)

    def test_an_action_with_no_dispositions_still_completes(self, backend):
        assert _executor(backend, 0)._resolve_completion_status(ACTION) == (ActionStatus.COMPLETED)

    def test_a_record_level_passthrough_alone_is_not_a_node_level_skip(self, backend):
        """A per-record passthrough is not a statement about the whole action."""
        backend.set_disposition(
            action_name=ACTION,
            record_id="guid-1",
            disposition=DISPOSITION_PASSTHROUGH,
            reason="guard_skip",
        )
        assert _executor(backend, 0)._resolve_completion_status(ACTION) == (ActionStatus.COMPLETED)
