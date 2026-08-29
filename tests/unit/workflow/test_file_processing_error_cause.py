"""The error raised when every input file fails must name why they failed.

That exception is what the CLI prints and what ``_handle_run_failure`` stores
as the node-level ``failed`` disposition, so a cause it omits reaches the log
file and nothing else.  All three collectors (storage backend, merged
upstreams, single directory) collect and drop the causes the same way.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError
from agent_actions.errors.configuration import FunctionNotFoundError
from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import process_files

ACTION = "collect_questions"
CAUSE = "Function 'write_rows' not found"

# The CLI summary panel prints ``error_message[:80]`` (cli/renderers/
# execution_renderer.py), so a cause appended after the counts is invisible
# there even once it is in the message.
SUMMARY_PANEL_WIDTH = 80


def _failing_strategy(exc: Exception) -> MagicMock:
    strategy = MagicMock()
    strategy.execute.side_effect = exc
    return strategy


def _params(strategy, upstream_dirs: list[str], output_dir: Path) -> FileProcessParams:
    return FileProcessParams(
        action_config={"agent_type": "test"},
        action_name=ACTION,
        strategy=strategy,
        upstream_data_dirs=upstream_dirs,
        output_directory=str(output_dir),
        idx=0,
    )


def _write(path: Path, payload: object = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload if payload is not None else [{"id": 1}]))
    return path


def _backend_runner(relative_paths: list[str]) -> ActionRunner:
    """Runner whose backend serves ``relative_paths`` for every upstream action."""
    backend = MagicMock()
    backend.list_target_files.return_value = relative_paths
    backend.read_target.return_value = [{"id": 1}]
    backend.get_disposition.return_value = []
    backend.load_metadata.return_value = None
    return ActionRunner(use_tools=True, storage_backend=backend)


class TestTheSurfacedErrorNamesTheRealCause:
    """Every collector must put its per-file causes into the raised message."""

    def test_the_storage_backend_path_names_the_file_and_the_cause(self, tmp_path):
        runner = _backend_runner(["data.json"])
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(tmp_path / "target" / "author_stem")],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        message = str(exc_info.value)
        assert CAUSE in message
        assert "data.json" in message

    def test_the_merged_upstream_path_names_the_file_and_the_cause(self, tmp_path):
        first = tmp_path / "target" / "dep1"
        second = tmp_path / "target" / "dep2"
        _write(first / "a.json")
        _write(second / "b.json")
        runner = ActionRunner(use_tools=True)
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(first), str(second)],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        message = str(exc_info.value)
        assert CAUSE in message
        assert "a.json" in message or "b.json" in message

    def test_the_single_directory_path_names_the_file_and_the_cause(self, tmp_path):
        source = tmp_path / "input"
        _write(source / "page.json")
        runner = ActionRunner(use_tools=True)
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(source)],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        message = str(exc_info.value)
        assert CAUSE in message
        assert "page.json" in message

    def test_the_generic_advice_replaces_nothing(self, tmp_path):
        """ "Check logs for details" must not survive as the whole explanation."""
        runner = _backend_runner(["data.json"])
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(tmp_path / "target" / "author_stem")],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        assert "Check logs for details" not in str(exc_info.value)


class TestTheCauseIsWhereTheReaderLooks:
    def test_the_cause_precedes_the_counts(self, tmp_path):
        """The summary panel truncates at 80 chars — the cause must fit inside."""
        runner = _backend_runner(["data.json"])
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(tmp_path / "target" / "author_stem")],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        assert CAUSE in str(exc_info.value)[:SUMMARY_PANEL_WIDTH]

    def test_many_failures_are_sampled_and_counted(self, tmp_path):
        source = tmp_path / "input"
        for i in range(5):
            _write(source / f"page{i}.json")
        runner = ActionRunner(use_tools=True)
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(source)],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)

        message = str(exc_info.value)
        assert "(and 2 more)" in message
        assert message.count(CAUSE) == 3


class TestTheCauseReachesTheStoredDisposition:
    """The node-level ``failed`` reason is what ``agac dispositions`` shows."""

    def test_the_stored_reason_names_the_cause(self, tmp_path):
        backend = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
        backend.initialize()
        source = tmp_path / "input"
        _write(source / "page.json")
        runner = ActionRunner(use_tools=True, storage_backend=backend)
        params = _params(
            _failing_strategy(FunctionNotFoundError(CAUSE)),
            [str(source)],
            tmp_path / "out",
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, params)
        raised = exc_info.value

        deps = MagicMock(spec=ExecutorDependencies)
        deps.state_manager = MagicMock()
        deps.action_runner = MagicMock()
        deps.action_runner.storage_backend = backend
        executor = ActionExecutor(deps)
        executor._handle_run_failure(
            ActionRunParams(
                action_name=ACTION,
                action_idx=0,
                action_config={"kind": "tool"},
                is_last_action=True,
                start_time=datetime.now(),
            ),
            raised,
        )

        rows = backend.get_disposition(
            ACTION, record_id=NODE_LEVEL_RECORD_ID, disposition=DISPOSITION_FAILED
        )
        backend.close()
        assert len(rows) == 1
        assert CAUSE in rows[0]["reason"]


class TestOnlyFailingRunsAreAffected:
    def test_a_run_that_processes_its_files_raises_nothing(self, tmp_path):
        source = tmp_path / "input"
        _write(source / "page.json")
        runner = ActionRunner(use_tools=True)
        params = _params(MagicMock(), [str(source)], tmp_path / "out")

        process_files(runner, params)

    def test_a_partial_failure_still_raises_nothing(self, tmp_path):
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy = MagicMock()
        calls: list[str] = []

        def execute(exec_params):
            calls.append(exec_params.file_path)
            if "bad.json" in exec_params.file_path:
                raise FunctionNotFoundError(CAUSE)

        strategy.execute.side_effect = execute
        runner = ActionRunner(use_tools=True)

        process_files(runner, _params(strategy, [str(source)], tmp_path / "out"))

        assert len(calls) == 2
