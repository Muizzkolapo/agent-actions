"""A reader skipped because its upstream holds nothing holds nothing either (1230).

A skip never rewrites the reader's output, so rows it stored before stand unless
the skip removes them. A real store is used: what a guard that filters everything
leaves behind is a target file with zero rows, and whether that counts as "holds
nothing" is a property of the store, not of a mock.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.output import AllVersionsFilteredError
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus

UPSTREAM = "flatten"
READER = "enrich"
FILE = "pages.json"


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [UPSTREAM, READER])


def _executor(backend, state_manager) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [UPSTREAM, READER]
    deps.action_runner.retried_records = frozenset()
    deps.output_manager = MagicMock()
    deps.skip_evaluator = MagicMock()
    deps.batch_manager = MagicMock()
    return ActionExecutor(deps)


def _rows(backend, action) -> int:
    return sum(len(backend._read_target_raw(action, p)) for p in backend.list_target_files(action))


def _stored(n: int, *, with_guid: bool = True) -> list[dict]:
    return [
        {**({"source_guid": f"g{i}"} if with_guid else {}), "content": {"x": {"i": i}}}
        for i in range(n)
    ]


def _reader_holds_six(backend):
    backend._write_target_raw(READER, FILE, _stored(6))


_RUN = {"action_idx": 1, "action_config": {"dependencies": [UPSTREAM]}, "is_last_action": True}


def _skip_reader(executor):
    return executor.execute_action_sync(READER, **_RUN)


def _upstream_filtered_everything(backend, state_manager):
    # What a guard that filters every record leaves: a file entry with no rows.
    backend._write_target_raw(UPSTREAM, FILE, [])
    state_manager.update_status(UPSTREAM, ActionStatus.SKIPPED)


def test_an_upstream_that_filtered_everything_empties_its_reader(backend, state_manager):
    _upstream_filtered_everything(backend, state_manager)
    _reader_holds_six(backend)

    result = _skip_reader(_executor(backend, state_manager))

    assert result.status == ActionStatus.SKIPPED
    assert backend.has_disposition(READER, DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID)
    assert _rows(backend, READER) == 0
    assert backend.list_target_files(UPSTREAM) == [FILE], "the upstream's own entry is not ours"


@pytest.mark.asyncio
async def test_the_async_path_empties_it_too(backend, state_manager):
    _upstream_filtered_everything(backend, state_manager)
    _reader_holds_six(backend)

    result = await _executor(backend, state_manager).execute_action_async(READER, **_RUN)

    assert result.status == ActionStatus.SKIPPED
    assert _rows(backend, READER) == 0


def test_an_upstream_that_failed_but_carries_its_rows_leaves_the_reader_standing(
    backend, state_manager
):
    backend._write_target_raw(UPSTREAM, FILE, _stored(6))
    state_manager.update_status(UPSTREAM, ActionStatus.FAILED)
    _reader_holds_six(backend)

    result = _skip_reader(_executor(backend, state_manager))

    assert result.status == ActionStatus.SKIPPED
    assert _rows(backend, READER) == 6


def test_rows_without_a_source_guid_are_still_rows(backend, state_manager):
    """'Does the upstream hold anything' must not depend on identities: a row stored
    without source_guid is stored whole and is still output the reader was built from."""
    backend._write_target_raw(UPSTREAM, FILE, _stored(6, with_guid=False))
    state_manager.update_status(UPSTREAM, ActionStatus.FAILED)
    _reader_holds_six(backend)

    _skip_reader(_executor(backend, state_manager))

    assert _rows(backend, READER) == 6


def test_a_merge_whose_every_version_is_empty_keeps_no_rows(backend, state_manager):
    """The other skip that never rewrites: _handle_all_versions_filtered."""
    backend._write_target_raw("merge", FILE, _stored(3))
    params = ActionRunParams(
        action_name="merge",
        action_idx=2,
        action_config={"version_consumption_config": {"source": "draft", "pattern": "merge"}},
        is_last_action=True,
        start_time=datetime.now(),
    )

    result = _executor(backend, state_manager)._handle_all_versions_filtered(
        params, AllVersionsFilteredError("merge", ["draft_1", "draft_2"])
    )

    assert result.status == ActionStatus.SKIPPED
    assert _rows(backend, "merge") == 0
    # Forgetting clears every disposition; the skip it records has to come after.
    assert backend.has_disposition("merge", DISPOSITION_SKIPPED, record_id=NODE_LEVEL_RECORD_ID)


def test_a_merge_skipped_during_a_repair_keeps_its_rows(backend, state_manager):
    """A retry touches only the records it names, on this skip as on the other."""
    backend._write_target_raw("merge", FILE, _stored(3))
    executor = _executor(backend, state_manager)
    executor.deps.action_runner.retried_records = frozenset({"g0"})
    params = ActionRunParams(
        action_name="merge",
        action_idx=2,
        action_config={"version_consumption_config": {"source": "draft", "pattern": "merge"}},
        is_last_action=True,
        start_time=datetime.now(),
    )

    executor._handle_all_versions_filtered(
        params, AllVersionsFilteredError("merge", ["draft_1", "draft_2"])
    )

    assert _rows(backend, "merge") == 3
