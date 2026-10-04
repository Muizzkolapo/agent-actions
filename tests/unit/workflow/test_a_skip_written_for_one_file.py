"""A node-level skip written for one input file decides nothing while the action holds rows.

The online collector writes it per file; the executor reads it once the whole
action has run. With rows stored, the action is classified on its records like
any other run, so a failure in another file still reads as one.

The skip is written by the collector's own check, the rest through the real
backend's write APIs, and the action is classified by the real executor.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.processing.result_collector import CollectionStats
from agent_actions.storage.backend import (
    DISPOSITION_FAILED,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    NODE_LEVEL_RECORD_ID,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


def _executor(backend):
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    return ActionExecutor(deps)


def _one_file_wholly_filtered(backend, other=()):
    filtered = [{"page_content": f"page {i}"} for i in range(3)]
    CollectionStats(filtered=len(filtered)).raise_if_terminal_failure(ACTION, filtered, [], backend)
    backend.write_target(ACTION, "pages.json", [])
    backend.write_target(ACTION, "other.json", list(other))


def _classify(backend):
    return _executor(backend)._resolve_completion_status(ACTION)


def _node_skipped(backend):
    return backend.has_disposition(ACTION, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID)


def test_an_action_that_holds_no_row_is_skipped(backend):
    _one_file_wholly_filtered(backend)

    assert _classify(backend) == ActionStatus.SKIPPED
    assert _node_skipped(backend)


def test_an_action_holding_rows_from_another_file_completes_and_the_skip_is_cleared(backend):
    _one_file_wholly_filtered(backend, other=[{"source_guid": "g1"}])
    backend.set_disposition(ACTION, "g1", DISPOSITION_SUCCESS)

    assert _classify(backend) == ActionStatus.COMPLETED
    assert not _node_skipped(backend)


def test_a_failure_beside_a_success_in_another_file_completes_with_failures(backend):
    _one_file_wholly_filtered(backend, other=[{"source_guid": "g1"}, {"source_guid": "g2"}])
    backend.set_disposition(ACTION, "g1", DISPOSITION_SUCCESS)
    backend.set_disposition(ACTION, "g2", DISPOSITION_FAILED, reason="down")

    assert _classify(backend) == ActionStatus.COMPLETED_WITH_FAILURES
    assert not _node_skipped(backend)


def test_another_file_holding_only_failures_fails_the_action(backend):
    """Its tombstones are rows, so the skip yields and the failures decide."""
    _one_file_wholly_filtered(backend, other=[{"source_guid": "g1"}])
    backend.set_disposition(ACTION, "g1", DISPOSITION_FAILED, reason="down")

    assert _classify(backend) == ActionStatus.FAILED
    assert not _node_skipped(backend)


def test_rows_stored_before_their_count_was_kept_are_held(backend):
    """A store older than record_count leaves it NULL on rows that hold records, so
    a summed count reads them as none."""
    _one_file_wholly_filtered(backend, other=[{"source_guid": "g1"}])
    backend.set_disposition(ACTION, "g1", DISPOSITION_SUCCESS)
    backend.connection.execute(
        "UPDATE target_data SET record_count = NULL WHERE relative_path = 'other.json'"
    )
    backend.connection.commit()

    assert _classify(backend) == ActionStatus.COMPLETED
    assert not _node_skipped(backend)
