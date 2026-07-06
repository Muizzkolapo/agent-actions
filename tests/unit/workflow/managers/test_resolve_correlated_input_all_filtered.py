"""All version branches filtered must cascade-skip, not crash.

When every version source of a version-consumption action produced no output,
``resolve_correlated_input`` raises ``AllVersionsFilteredError`` (not
``ConfigurationError``) and the executor resolves the action as SKIPPED so the
pipeline continues instead of exiting non-zero.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.record.reasons import ALL_VERSIONS_FILTERED
from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.workflow.managers.output import (
    ActionOutputManager,
    AllVersionsFilteredError,
    OutputManagerConfig,
)
from agent_actions.workflow.managers.state import ActionStatus


def _make_manager(version_sources: list[str], storage_backend: MagicMock) -> ActionOutputManager:
    correlator = MagicMock()
    correlator.detect_explicit_version_consumption.return_value = {
        "consumer": {"version_agents": version_sources, "pattern": "merge"}
    }
    correlator.prepare_correlated_input.return_value = None  # nothing correlated
    config = OutputManagerConfig(
        agent_folder=Path("."),
        execution_order=[*version_sources, "consumer"],
        action_configs={},
        action_status={},
        version_correlator=correlator,
        console=MagicMock(),
        storage_backend=storage_backend,
    )
    return ActionOutputManager(config)


def test_all_sources_empty_raises_all_versions_filtered_error():
    backend = MagicMock()
    backend.list_target_files.return_value = []  # every version source empty
    mgr = _make_manager(["v1", "v2"], backend)
    with pytest.raises(AllVersionsFilteredError) as exc:
        mgr.resolve_correlated_input(2)  # idx of "consumer"
    assert "consumer" in str(exc.value)
    assert exc.value.version_sources == ["v1", "v2"]


def test_some_source_has_output_raises_configuration_error():
    """A source produced output but correlation still failed → keep the loud error."""
    backend = MagicMock()
    backend.list_target_files.side_effect = lambda a: ["out.json"] if a == "v1" else []
    mgr = _make_manager(["v1", "v2"], backend)
    with pytest.raises(ConfigurationError):
        mgr.resolve_correlated_input(2)


def _make_executor(version_sources: list[str]):
    from agent_actions.workflow.executor import (
        ActionExecutor,
        ActionRunParams,
        ExecutorDependencies,
    )

    deps = ExecutorDependencies(
        action_runner=MagicMock(),
        state_manager=MagicMock(),
        skip_evaluator=MagicMock(),
        batch_manager=MagicMock(),
        output_manager=MagicMock(),
    )
    deps.output_manager.resolve_correlated_input.side_effect = AllVersionsFilteredError(
        "consumer", version_sources
    )
    deps.action_runner.execution_order = [*version_sources, "consumer"]
    executor = ActionExecutor(deps, console=MagicMock())
    params = ActionRunParams(
        action_name="consumer",
        action_idx=len(version_sources),
        action_config={},
        is_last_action=True,
        start_time=datetime.now(),
    )
    return executor, params, deps


def test_executor_cascade_skips_instead_of_crashing():
    executor, params, _ = _make_executor(["v1", "v2"])
    result = executor._execute_action_run(params)  # must NOT raise
    assert result.status == ActionStatus.SKIPPED
    assert result.success is True


def test_executor_writes_node_level_skip_disposition():
    executor, params, deps = _make_executor(["v1", "v2"])
    executor._execute_action_run(params)
    set_disposition = deps.action_runner.storage_backend.set_disposition
    set_disposition.assert_called_once()
    kwargs = set_disposition.call_args.kwargs
    assert kwargs["record_id"] == NODE_LEVEL_RECORD_ID
    assert kwargs["disposition"] == DISPOSITION_SKIPPED
    assert kwargs["reason"] == ALL_VERSIONS_FILTERED
    assert "v1" in kwargs["detail"]
    assert "v2" in kwargs["detail"]


def test_executor_cascade_skip_survives_disposition_write_error():
    """A storage error while recording the skip must not re-crash the cascade-skip path."""
    executor, params, deps = _make_executor(["v1", "v2"])
    deps.action_runner.storage_backend.set_disposition.side_effect = RuntimeError("db locked")
    result = executor._execute_action_run(params)  # must NOT raise
    assert result.status == ActionStatus.SKIPPED
    assert result.success is True


def test_executor_async_cascade_skip_survives_disposition_write_error():
    executor, params, deps = _make_executor(["v1", "v2"])
    deps.action_runner.storage_backend.set_disposition.side_effect = RuntimeError("db locked")
    result = asyncio.run(executor._execute_action_run_async(params))  # must NOT raise
    assert result.status == ActionStatus.SKIPPED
    assert result.success is True
