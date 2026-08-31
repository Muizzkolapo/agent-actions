"""An action-fatal error must escape ``process_files`` even when other files succeeded.

The processing loops re-raise these deliberately — an ``on_exhausted: raise``
halt, or an error they marked action-fatal — and the per-file collector must
not flatten that escalation into a log line just because another file
processed. It finishes the pass, then raises, so the executor records the
failure and the resume paths work. Errors nobody declared fatal, including the
same types raised from elsewhere, stay per-file tolerated.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import (
    AgentActionsError,
    ConfigurationError,
    ConfigValidationError,
    DependencyError,
    EmptyOutputError,
    exhaustion_halt,
    mark_action_fatal,
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


def _declared(error: Exception) -> AgentActionsError:
    """A marked strategy error, wrapped the way the pipeline delivers it."""
    return AgentActionsError(f"Error generating target: {error}", cause=mark_action_fatal(error))


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


def _strategy_failing_on(failures: dict[str, Exception]) -> tuple[MagicMock, list[str]]:
    """A strategy raising ``failures[name]`` for the file whose path contains *name*."""
    strategy = MagicMock()
    calls: list[str] = []

    def execute(exec_params):
        calls.append(Path(exec_params.file_path).name)
        for name, exc in failures.items():
            if name in exec_params.file_path:
                raise exc

    strategy.execute.side_effect = execute
    return strategy, calls


class TestAnActionFatalErrorEscapesPartialSuccess:
    def test_a_halt_is_raised_not_swallowed(self, tmp_path):
        """One file succeeds, the other hits on_exhausted: raise — the halt must surface."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "exhausted.json")
        strategy, calls = _strategy_failing_on({"exhausted.json": exhaustion_halt(HALT_TEXT)})

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
            )

        assert raised_by_exhaustion_policy(exc_info.value), (
            "the raised error lost the on_exhausted tag, so the executor "
            "cannot write the halt marker"
        )
        assert "exhausted.json" in str(exc_info.value)
        assert sorted(calls) == ["exhausted.json", "good.json"]

    @pytest.mark.parametrize(
        "fatal",
        [ConfigurationError(CONFIG_TEXT), EmptyOutputError("no output with on_empty=error")],
        ids=["configuration_error", "empty_output_error"],
    )
    def test_a_declared_error_is_raised_through_the_pipeline_wrapper(self, tmp_path, fatal):
        """The collector sees the wrapper, so the declaration must be read from the chain."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy, calls = _strategy_failing_on({"bad.json": _declared(fatal)})

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
        strategy, calls = _strategy_failing_on({"exhausted.json": exhaustion_halt(HALT_TEXT)})

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
        strategy, calls = _strategy_failing_on({"exhausted.json": exhaustion_halt(HALT_TEXT)})

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True),
                _params(strategy, [str(first), str(second)], tmp_path / "out"),
            )

        assert raised_by_exhaustion_policy(exc_info.value)
        assert sorted(calls) == ["exhausted.json", "good.json"]


class TestTheHaltIsTheCauseThatSurvives:
    def test_a_halt_outranks_an_earlier_fatal_and_the_walk_completes(self, tmp_path):
        """The halt carries the policy tag, so it must be the chained cause.

        The non-halt error is walked first, so a collector that kept the first
        fatal it saw, or abandoned the walk at the first one, loses the halt.
        """
        source = tmp_path / "input"
        _write(source / "a_config.json")
        _write(source / "b_halt.json")
        _write(source / "c_ok.json")
        strategy, calls = _strategy_failing_on(
            {
                "a_config.json": _declared(ConfigurationError(CONFIG_TEXT)),
                "b_halt.json": exhaustion_halt(HALT_TEXT),
            }
        )

        with pytest.raises(DependencyError) as exc_info:
            process_files(
                ActionRunner(use_tools=True), _params(strategy, [str(source)], tmp_path / "out")
            )

        assert raised_by_exhaustion_policy(exc_info.value), (
            "the earlier ConfigurationError displaced the halt, so the halt "
            "marker is lost and the action would be re-run at the same cost"
        )
        assert "b_halt.json" in str(exc_info.value)
        assert sorted(calls) == ["a_config.json", "b_halt.json", "c_ok.json"], (
            "the pass abandoned files after the first action-fatal error"
        )


class TestUndeclaredFailuresStayTolerated:
    @pytest.mark.parametrize(
        "error",
        [
            ValueError("unreadable row"),
            RecordContextError("record context incomplete"),
            ConfigValidationError(
                "Staging data field(s) 'source' collide with reserved namespace names."
            ),
            ConfigurationError("raised outside a record loop"),
        ],
        ids=["file_scoped", "record_context", "staging_data", "undeclared_configuration"],
    )
    def test_an_undeclared_error_still_returns_partial(self, tmp_path, error):
        """Only a declared error stops the action; a bad input file does not."""
        source = tmp_path / "input"
        _write(source / "good.json")
        _write(source / "bad.json")
        strategy, calls = _strategy_failing_on({"bad.json": error})

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
        strategy, _ = _strategy_failing_on({"exhausted.json": exhaustion_halt(HALT_TEXT)})
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
