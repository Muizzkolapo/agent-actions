"""Version-merge with no correlatable input is classified by cause.

When every version source was guard-filtered, ``resolve_correlated_input`` raises
``AllVersionsFilteredError`` so the executor cascade-skips instead of crashing.
Sources that produced records (genuine correlation failure) or that are empty for
a non-filter reason (missing data) raise ``ConfigurationError``.
"""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.record.reasons import ALL_VERSIONS_FILTERED
from agent_actions.storage.backend import (
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
    NODE_LEVEL_RECORD_ID,
)
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


def _backend(
    *,
    records: dict[str, list] | None = None,
    skipped: tuple[str, ...] = (),
    filtered_records: tuple[str, ...] = (),
    disposition_error: bool = False,
) -> MagicMock:
    """Backend mock keyed by output records, node-level skip markers, and per-record filter dispositions."""
    records = records or {}
    skipped_set = set(skipped)
    filtered_records_set = set(filtered_records)

    def list_target_files(action_name: str) -> list[str]:
        return ["out.json"] if action_name in records else []

    def read_target(action_name: str, _relative_path: str) -> list:
        return records.get(action_name, [])

    def has_disposition(action_name: str, disposition: str, record_id=None) -> bool:
        if disposition_error:
            raise sqlite3.Error("disposition probe failed")
        if disposition == DISPOSITION_SKIPPED and record_id == NODE_LEVEL_RECORD_ID:
            return action_name in skipped_set
        if disposition == DISPOSITION_FILTERED and record_id is None:
            return action_name in filtered_records_set
        return False

    backend = MagicMock()
    backend.list_target_files.side_effect = list_target_files
    backend.read_target.side_effect = read_target
    backend.has_disposition.side_effect = has_disposition
    return backend


def test_all_sources_skipped_raises_all_versions_filtered_error():
    mgr = _make_manager(["v1", "v2"], _backend(skipped=("v1", "v2")))
    with pytest.raises(AllVersionsFilteredError) as exc:
        mgr.resolve_correlated_input(2)  # idx of "consumer"
    assert "consumer" in str(exc.value)
    assert exc.value.version_sources == ["v1", "v2"]


def test_skipped_source_with_empty_output_file_still_skips():
    """A skipped branch that wrote an empty output file has files but zero records → skip, not crash."""
    mgr = _make_manager(["v1", "v2"], _backend(records={"v1": [], "v2": []}, skipped=("v1", "v2")))
    with pytest.raises(AllVersionsFilteredError):
        mgr.resolve_correlated_input(2)


def test_some_source_has_output_raises_configuration_error():
    """A source produced records but correlation still failed → keep the loud error."""
    mgr = _make_manager(["v1", "v2"], _backend(records={"v1": [{"id": 1}]}, skipped=("v2",)))
    with pytest.raises(ConfigurationError) as exc:
        mgr.resolve_correlated_input(2)
    assert "v1" in str(exc.value)


def test_all_empty_but_not_skipped_raises_configuration_error():
    """No records anywhere and no node-level skip → missing data surfaces loudly, no silent skip."""
    mgr = _make_manager(["v1", "v2"], _backend(skipped=()))
    with pytest.raises(ConfigurationError) as exc:
        mgr.resolve_correlated_input(2)
    assert "v1" in str(exc.value)
    assert "v2" in str(exc.value)


def test_per_record_filtered_without_node_skip_raises_not_masks():
    """Records filtered per-record but no node-level skip (e.g. crashed mid-run) → raise, don't cascade-skip."""
    mgr = _make_manager(["v1", "v2"], _backend(filtered_records=("v1", "v2")))
    with pytest.raises(ConfigurationError):
        mgr.resolve_correlated_input(2)


def test_disposition_probe_error_surfaces_storage_error_not_raw_crash():
    """A storage fault probing the skip marker surfaces a storage-specific error, not a raw crash or the missing-data message."""
    mgr = _make_manager(["v1", "v2"], _backend(disposition_error=True))
    with pytest.raises(ConfigurationError) as exc:
        mgr.resolve_correlated_input(2)
    assert "storage backend" in str(exc.value)
    assert "were not guard-filtered" not in str(exc.value)


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
