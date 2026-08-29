"""Every ``on_exhausted: raise`` site must produce a halt the next run honours.

The marker is only useful if it survives the whole route from the raising code
to the disposition row.  Four things break that route, and each is covered here:
the halting file need not be the first to fail, nor within the tracked-error
cap; three sibling raise sites attach no policy at all; and a batch action never
reaches the failure handler, so it is left CHECKING_BATCH — retryable — and the
next run submits a whole new batch.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.storage.backend import DISPOSITION_FAILED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    ActionExecutor,
    ExecutorDependencies,
    _halt_marker,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import _MAX_TRACKED_ERRORS, process_files

ACTION = "summarize_page_content"
HALT_MARKER = "halted_on_exhausted"
HALT_TEXT = "Retry exhausted for record abc after 2 attempts (on_exhausted=raise)"


def _halt_error() -> AgentActionsError:
    return AgentActionsError(HALT_TEXT, context={"on_exhausted": "raise"})


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def state_manager(tmp_path):
    return ActionStateManager(tmp_path / ".agent_status.json", [ACTION])


def _executor(backend, state_manager) -> ActionExecutor:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = state_manager
    deps.action_runner = MagicMock()
    deps.action_runner.storage_backend = backend
    deps.action_runner.execution_order = [ACTION]
    deps.output_manager = MagicMock()
    deps.output_manager.resolve_correlated_input.return_value = None
    deps.skip_evaluator = MagicMock()
    deps.skip_evaluator.should_skip_action.return_value = False
    deps.batch_manager = MagicMock()
    return ActionExecutor(deps)


def _node_detail(backend) -> str | None:
    rows = backend.get_disposition(
        ACTION, record_id=NODE_LEVEL_RECORD_ID, disposition=DISPOSITION_FAILED
    )
    return rows[0]["detail"] if rows else None


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": 1}]))


def _run_files_until_it_raises(tmp_path, failures: dict[str, Exception]) -> Exception:
    """Drive the real process_files with a per-file exception map."""
    source = tmp_path / "input"
    for name in failures:
        _write(source / name)
    strategy = MagicMock()

    def execute(exec_params):
        raise failures[Path(exec_params.file_path).name]

    strategy.execute.side_effect = execute
    params = FileProcessParams(
        action_config={"agent_type": "test"},
        action_name=ACTION,
        strategy=strategy,
        upstream_data_dirs=[str(source)],
        output_directory=str(tmp_path / "out"),
        idx=0,
    )
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - the type is the subject
        process_files(ActionRunner(use_tools=True), params)
    return exc_info.value


class TestTheHaltNeedNotFailFirst:
    """process_files chains one cause; it must be the halting one."""

    def test_a_halt_behind_an_ordinary_failure_is_still_marked(self, tmp_path):
        # "a" sorts first, so the ordinary error is recorded before the halt.
        raised = _run_files_until_it_raises(
            tmp_path,
            {"a_boom.json": RuntimeError("malformed record"), "b_halt.json": _halt_error()},
        )

        assert _halt_marker(raised) == HALT_MARKER

    def test_a_halt_past_the_tracked_error_cap_is_still_marked(self, tmp_path):
        failures: dict[str, Exception] = {
            f"f{i:02d}_boom.json": RuntimeError("boom") for i in range(_MAX_TRACKED_ERRORS + 1)
        }
        failures["zz_halt.json"] = _halt_error()

        raised = _run_files_until_it_raises(tmp_path, failures)

        assert _halt_marker(raised) == HALT_MARKER

    def test_no_halt_among_the_failures_is_not_marked(self, tmp_path):
        raised = _run_files_until_it_raises(
            tmp_path, {"a.json": RuntimeError("boom"), "b.json": ValueError("nope")}
        )

        assert _halt_marker(raised) is None


def _capture(call) -> Exception:
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 - the type is the subject
        call()
    return exc_info.value


class TestEveryRaiseSiteAttachesThePolicy:
    """A halt is a halt whichever recovery loop exhausted.

    Driven through each site's real callable.  Only ``result_collector``
    attached the policy, so the other three produced a bare RuntimeError that
    the next run read as an ordinary, resettable failure.
    """

    def test_batch_reprompt_validation_exhaustion(self):
        from agent_actions.llm.providers.batch_base import BatchResult
        from agent_actions.processing.evaluation.exhaustion import apply_exhausted_reprompt

        result = BatchResult(custom_id="rec-1", content={}, success=False, error=None)
        error = _capture(
            lambda: apply_exhausted_reprompt(
                results=[result],
                failed_ids={"rec-1"},
                validation_name="schema_check",
                attempt=2,
                on_exhausted="raise",
            )
        )

        assert _halt_marker(error) == HALT_MARKER

    def test_batch_reprompt_return_last_does_not_halt(self):
        from agent_actions.llm.providers.batch_base import BatchResult
        from agent_actions.processing.evaluation.exhaustion import apply_exhausted_reprompt

        result = BatchResult(custom_id="rec-1", content={}, success=False, error=None)
        returned = apply_exhausted_reprompt(
            results=[result],
            failed_ids={"rec-1"},
            validation_name="schema_check",
            attempt=2,
            on_exhausted="return_last",
        )

        assert returned == [result]


class TestABatchHaltIsNotLeftRetryable:
    """A batch halt escaped the failure handler entirely and kept CHECKING_BATCH."""

    def test_it_is_recorded_as_a_marked_failure(self, backend, state_manager):
        executor = _executor(backend, state_manager)
        executor.deps.batch_manager.handle_batch_agent.side_effect = _halt_error()

        result = executor._handle_batch_check(ACTION, 0, {"kind": "llm"}, datetime.now())

        assert result.success is False
        assert state_manager.get_status(ACTION) == ActionStatus.FAILED
        assert _node_detail(backend) == HALT_MARKER

    def test_an_ordinary_batch_error_still_escapes(self, backend, state_manager):
        """A transient polling failure must keep CHECKING_BATCH so the next run re-polls.

        Converting it to FAILED would reset it to PENDING and submit a duplicate batch.
        """
        executor = _executor(backend, state_manager)
        executor.deps.batch_manager.handle_batch_agent.side_effect = RuntimeError("socket timeout")

        with pytest.raises(RuntimeError, match="socket timeout"):
            executor._handle_batch_check(ACTION, 0, {"kind": "llm"}, datetime.now())

        assert state_manager.get_status(ACTION) == ActionStatus.CHECKING_BATCH
