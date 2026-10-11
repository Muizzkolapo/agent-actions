"""A walk that finds no input file says so, and the action is skipped holding nothing (1240).

The walk returned quietly and the action completed without writing, which left the
rows it stored before standing. Only the walk knows it found nothing, so it raises,
and the executor skips the action the way it skips a merge with no version to read.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from agent_actions.record.reasons import NO_INPUT_FILES
from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ActionRunParams, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import NoInputFilesError, process_files

ACTION = "flatten"
FILE = "pages.json"


def _params(dirs, *, action_config=None, file_type_filter=None) -> FileProcessParams:
    return FileProcessParams(
        action_config=action_config or {},
        action_name=ACTION,
        strategy=MagicMock(),
        upstream_data_dirs=[str(d) for d in dirs],
        output_directory="out",
        idx=0,
        file_type_filter=file_type_filter,
    )


def _empty(path):
    path.mkdir(parents=True)
    return path


class TestTheWalkSaysItFoundNothing:
    def test_an_empty_directory(self, tmp_path):
        with pytest.raises(NoInputFilesError) as raised:
            process_files(ActionRunner(use_tools=True), _params([_empty(tmp_path / "in")]))

        assert raised.value.action_name == ACTION

    def test_a_directory_that_is_not_there(self, tmp_path):
        with pytest.raises(NoInputFilesError):
            process_files(ActionRunner(use_tools=True), _params([tmp_path / "gone"]))

    def test_several_upstreams_none_holding_a_file(self, tmp_path):
        dirs = [_empty(tmp_path / "target" / "a"), _empty(tmp_path / "target" / "b")]

        with pytest.raises(NoInputFilesError):
            process_files(ActionRunner(use_tools=True), _params(dirs))

    def test_files_the_action_does_not_read_are_not_input(self, tmp_path):
        staged = _empty(tmp_path / "in")
        (staged / "notes.csv").write_text("a,b\n")

        with pytest.raises(NoInputFilesError):
            process_files(
                ActionRunner(use_tools=True), _params([staged], file_type_filter={"json"})
            )

    def test_under_a_file_limit_too(self, tmp_path):
        """A limit stops a walk only after it has taken a file."""
        with pytest.raises(NoInputFilesError):
            process_files(
                ActionRunner(use_tools=True),
                _params([_empty(tmp_path / "in")], action_config={"file_limit": 1}),
            )

    def test_not_under_a_repair(self, tmp_path):
        """A repair touches only the records it names, so finding none of their files
        is no reason to delete the rest."""
        runner = ActionRunner(use_tools=True)
        runner.retried_records = frozenset({"g0"})

        process_files(runner, _params([_empty(tmp_path / "in")]))


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _executor(backend, tmp_path) -> ActionExecutor:
    runner = MagicMock()
    runner.storage_backend = backend
    runner.execution_order = [ACTION]
    runner.retried_records = frozenset()
    runner.run_action.side_effect = NoInputFilesError(ACTION, ["staging"])
    output_manager = MagicMock()
    output_manager.resolve_correlated_input.return_value = None
    return ActionExecutor(
        deps=ExecutorDependencies(
            action_runner=runner,
            state_manager=ActionStateManager(tmp_path / ".agent_status.json", [ACTION]),
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=output_manager,
        )
    )


def _run_params() -> ActionRunParams:
    return ActionRunParams(
        action_name=ACTION,
        action_idx=0,
        action_config={},
        is_last_action=True,
        start_time=datetime.now(),
    )


def _rows(backend) -> int:
    return sum(len(backend._read_target_raw(ACTION, p)) for p in backend.list_target_files(ACTION))


class TestTheActionIsSkippedHoldingNothing:
    def test_its_rows_go_and_the_skip_is_recorded(self, backend, tmp_path):
        backend.write_target(ACTION, FILE, [{"source_guid": f"g{i}"} for i in range(3)])
        executor = _executor(backend, tmp_path)

        result = executor._execute_action_run(_run_params())

        assert result.status == ActionStatus.SKIPPED
        assert result.success
        assert _rows(backend) == 0
        assert executor.deps.state_manager.get_status(ACTION) == ActionStatus.SKIPPED
        # Forgetting clears every disposition; the skip it records has to come after.
        rows = backend.get_disposition(
            ACTION, record_id=NODE_LEVEL_RECORD_ID, disposition=DISPOSITION_SKIPPED
        )
        assert [row.get("reason") for row in rows] == [NO_INPUT_FILES]

    def test_the_run_history_records_it_as_skipped(self, backend, tmp_path):
        executor = _executor(backend, tmp_path)
        executor.run_tracker = MagicMock()
        executor.run_id = "r"

        executor._execute_action_run(_run_params())

        tracked = executor.run_tracker.record_action_complete
        tracked.assert_called_once()
        config = tracked.call_args.kwargs["config"]
        assert (config.status, config.skip_reason) == ("skipped", NO_INPUT_FILES)

    @pytest.mark.asyncio
    async def test_the_async_path_does_the_same(self, backend, tmp_path):
        backend.write_target(ACTION, FILE, [{"source_guid": "g0"}])

        result = await _executor(backend, tmp_path)._execute_action_run_async(_run_params())

        assert result.status == ActionStatus.SKIPPED
        assert _rows(backend) == 0
