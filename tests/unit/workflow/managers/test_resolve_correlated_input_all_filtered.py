"""Version-merge with no correlatable input cascade-skips; it does not crash.

Classification is by record count against a real backend — not by dispositions
upstream code clears. When every version source produced zero records,
``prepare_correlated_input`` raises ``AllVersionsFilteredError`` and the executor
resolves the consumer as SKIPPED; a correlation or storage fault raises
``ConfigurationError``.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.record.reasons import ALL_VERSIONS_FILTERED
from agent_actions.storage.backend import DISPOSITION_SKIPPED, NODE_LEVEL_RECORD_ID
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.output import (
    ActionOutputManager,
    AllVersionsFilteredError,
    OutputManagerConfig,
)
from agent_actions.workflow.managers.state import ActionStatus

# A correlatable target record: the merge keys on version_correlation_id.
_RECORD = {
    "source_guid": "g1",
    "version_correlation_id": "c1",
    "target_id": "t1",
    "_state": "processed",
    "_state_schema_version": 1,
    "content": {"gen_1": {"score": 1}},
}


def _real_manager(tmp_path, source_records: dict[str, list]) -> tuple[ActionOutputManager, object]:
    """ActionOutputManager on a real SQLite backend + correlator.

    source_records maps each version source to the target records it wrote; an
    empty list models a source that wrote an empty output file (record_count=0).
    """
    version_sources = list(source_records)
    backend = SQLiteBackend.create(db_path=str(tmp_path / "store" / "t.db"), workflow_name="t")
    backend.initialize()
    for src, recs in source_records.items():
        backend._write_target_raw(src, "out.json", recs)
    base = version_sources[0].rsplit("_", 1)[0]
    action_configs: dict = {src: {"agent_type": base} for src in version_sources}
    action_configs["consumer"] = {
        "agent_type": "consumer",
        "version_consumption_config": {"source": base, "pattern": "merge"},
    }
    config = OutputManagerConfig(
        agent_folder=tmp_path,
        execution_order=[*version_sources, "consumer"],
        action_configs=action_configs,
        action_status={},
        version_correlator=VersionOutputCorrelator(tmp_path, storage_backend=backend),
        console=MagicMock(),
        storage_backend=backend,
    )
    return ActionOutputManager(config), backend


def _delegating_manager(version_sources: list[str], **prepare) -> ActionOutputManager:
    """Manager whose correlator.prepare_correlated_input is a configurable mock."""
    correlator = MagicMock()
    correlator.detect_explicit_version_consumption.return_value = {
        "consumer": {"version_agents": version_sources, "pattern": "merge"}
    }
    correlator.prepare_correlated_input.configure_mock(**prepare)
    config = OutputManagerConfig(
        agent_folder=Path("."),
        execution_order=[*version_sources, "consumer"],
        action_configs={},
        action_status={},
        version_correlator=correlator,
        console=MagicMock(),
        storage_backend=MagicMock(),
    )
    return ActionOutputManager(config)


def test_all_sources_empty_files_cascade_skip(tmp_path):
    """Every source wrote an empty output file (record_count=0) — cascade-skip, not crash.

    Reproduces the file-existence regression: the empty file is listed and the
    node-level skip marker is cleared by the executor, so only a record-count
    classifier survives this.
    """
    mgr, _ = _real_manager(tmp_path, {"gen_1": [], "gen_2": []})
    with pytest.raises(AllVersionsFilteredError) as exc:
        mgr.resolve_correlated_input(2)
    assert exc.value.version_sources == ["gen_1", "gen_2"]


def test_source_with_records_is_not_cascade_skipped(tmp_path):
    """At least one source produced records → correlate, do not cascade-skip."""
    mgr, _ = _real_manager(tmp_path, {"gen_1": [_RECORD], "gen_2": []})
    result = mgr.resolve_correlated_input(2)
    assert result is not None


def test_storage_fault_surfaces_configuration_error(tmp_path):
    """A backend read fault surfaces a clean ConfigurationError, not a raw sqlite crash."""
    mgr, backend = _real_manager(tmp_path, {"gen_1": [], "gen_2": []})
    backend.close()
    with pytest.raises(ConfigurationError):
        mgr.resolve_correlated_input(2)


def test_resolve_propagates_all_versions_filtered():
    """resolve_correlated_input propagates the correlator's cascade-skip signal."""
    mgr = _delegating_manager(
        ["v1", "v2"], side_effect=AllVersionsFilteredError("consumer", ["v1", "v2"])
    )
    with pytest.raises(AllVersionsFilteredError):
        mgr.resolve_correlated_input(2)


def test_resolve_returns_correlated_directory():
    mgr = _delegating_manager(["v1", "v2"], return_value="/tmp/correlated/consumer")
    assert mgr.resolve_correlated_input(2) == ["/tmp/correlated/consumer"]


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
