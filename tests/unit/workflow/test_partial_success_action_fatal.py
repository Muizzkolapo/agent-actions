"""An action-fatal error must escape ``process_files`` even when other files succeeded.

The processing strategies deliberately re-raise action-fatal errors — an
``on_exhausted: raise`` halt, ``ConfigurationError``, ``EmptyOutputError``,
``SchemaValidationError`` — out of their per-record loops. The per-file
collector must not flatten that escalation into a log line just because
another file processed; it finishes the pass (successes are checkpointed)
and then raises, so the executor records the failure and the resume paths
work. File-scoped accidents stay per-file tolerated.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import (
    ConfigurationError,
    DependencyError,
    EmptyOutputError,
    exhaustion_halt,
    raised_by_exhaustion_policy,
)
from agent_actions.errors.configuration import RecordContextError
from agent_actions.record.reasons import HALTED_ON_EXHAUSTED
from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.safe_format import get_error_chain
from agent_actions.workflow.executor import (
    ActionExecutor,
    ActionRunParams,
    ExecutorDependencies,
)
from agent_actions.workflow.managers.state import ActionStatus
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import process_files

ACTION = "collect_questions"
HALT_TEXT = "Retry exhausted for record r-2 after 2 attempts (on_exhausted=raise)"
CONFIG_TEXT = "Schema 'rf_label' not found for action"


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


def _strategy_failing_on(filename: str, exc: Exception) -> tuple[MagicMock, list[str]]:
    """A strategy that raises *exc* for the file whose path contains *filename*."""
    strategy = MagicMock()
    calls: list[str] = []

    def execute(exec_params):
        calls.append(Path(exec_params.file_path).name)
        if filename in exec_params.file_path:
            raise exc

    strategy.execute.side_effect = execute
    return strategy, calls


class TestAnActionFatalErrorEscapesPartialSuccess:
    def test_a_halt_is_raised_not_swallowed(self, tmp_path):
        """One file succeeds, the other hits on_exhausted: raise — the halt must surface."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "exhausted.json")
        strategy, calls = _strategy_failing_on("exhausted.json", exhaustion_halt(HALT_TEXT))

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
            )

        assert raised_by_exhaustion_policy(exc_info.value), (
            "the raised error lost the on_exhausted tag, so the executor "
            "cannot write the halt marker"
        )
        assert "exhausted.json" in str(exc_info.value)
        assert sorted(calls) == ["exhausted.json", "good.json"], (
            "the pass must finish every file before raising"
        )

    @pytest.mark.parametrize(
        "fatal",
        [
            ConfigurationError(CONFIG_TEXT),
            EmptyOutputError("action produced no output with on_empty=error"),
        ],
        ids=["configuration_error", "empty_output_error"],
    )
    def test_a_strategy_fatal_error_is_raised_not_swallowed(self, tmp_path, fatal):
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy, calls = _strategy_failing_on("bad.json", fatal)

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
            )

        assert any(link is fatal for link in get_error_chain(exc_info.value)), (
            "the original action-fatal error must stay on the raised chain"
        )
        assert "bad.json" in str(exc_info.value)
        assert sorted(calls) == ["bad.json", "good.json"]

    def test_the_storage_backend_path_raises_the_halt_too(self, tmp_path):
        backend = MagicMock()
        backend.list_target_files.return_value = ["good.json", "exhausted.json"]
        backend.read_target.return_value = [{"id": 1}]
        backend.get_disposition.return_value = []
        backend.load_metadata.return_value = None
        strategy, calls = _strategy_failing_on("exhausted.json", exhaustion_halt(HALT_TEXT))

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True, storage_backend=backend),
                _params(strategy, [str(tmp_path / "target" / "upstream")], tmp_path / "out"),
            )

        assert raised_by_exhaustion_policy(exc_info.value)
        assert sorted(calls) == ["exhausted.json", "good.json"]

    def test_the_merged_upstreams_path_raises_the_halt_too(self, tmp_path):
        first = tmp_path / "up1"
        second = tmp_path / "up2"
        _write(first / "good.json")
        _write(second / "exhausted.json")
        strategy, calls = _strategy_failing_on("exhausted.json", exhaustion_halt(HALT_TEXT))

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True),
                _params(strategy, [str(first), str(second)], tmp_path / "out"),
            )

        assert raised_by_exhaustion_policy(exc_info.value)
        assert sorted(calls) == ["exhausted.json", "good.json"]


class TestFileScopedFailuresStayTolerated:
    def test_an_ordinary_error_still_returns_partial(self, tmp_path):
        """A file-scoped accident is a per-file failure, not an action failure."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy, calls = _strategy_failing_on("bad.json", ValueError("unreadable row"))

        process_files(
            ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
        )

        assert sorted(calls) == ["bad.json", "good.json"]

    def test_a_record_context_error_still_returns_partial(self, tmp_path):
        """RecordContextError is per-record recoverable despite its ConfigurationError parent."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy, calls = _strategy_failing_on("bad.json", RecordContextError("context incomplete"))

        process_files(
            ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
        )

        assert sorted(calls) == ["bad.json", "good.json"]


class TestThePartialFailureIsRecorded:
    def test_a_partial_halt_reaches_status_failed_and_the_halt_marker(self, tmp_path):
        """What process_files raises must produce the same durable evidence as a full failure."""
        backend = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
        backend.initialize()
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "exhausted.json")
        strategy, _ = _strategy_failing_on("exhausted.json", exhaustion_halt(HALT_TEXT))
        runner = ActionRunner(use_tools=True, storage_backend=backend)

        with pytest.raises(DependencyError) as exc_info:
            process_files(runner, _params(strategy, [str(source)], tmp_path / "out"))
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
                action_config={"kind": "llm"},
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
        assert rows[0]["detail"] == HALTED_ON_EXHAUSTED
        status_update = deps.state_manager.update_status.call_args
        assert status_update.args[1] is ActionStatus.FAILED
