"""A tool action under run_mode: batch completes as an online action does.

The post-run check reads stored state for signs of a batch. A tool action with a
passthrough disposition on record must not be taken for a batch passthrough,
which records the action without its execution time.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.batch import BatchLifecycleManager
from agent_actions.workflow.managers.output import ActionOutputManager
from agent_actions.workflow.managers.skip import SkipEvaluator
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


def _executor(storage) -> tuple[ActionExecutor, MagicMock]:
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.state_manager.get_status.return_value = ActionStatus.PENDING
    deps.state_manager.get_status_details.return_value = {}
    deps.state_manager.adopt_truncation_marker.return_value = False
    deps.batch_manager = BatchLifecycleManager(
        job_manager=MagicMock(), processing_service=MagicMock(), storage_backend=storage
    )
    deps.skip_evaluator = MagicMock(spec=SkipEvaluator)
    deps.skip_evaluator.should_skip_action.return_value = False
    deps.output_manager = MagicMock(spec=ActionOutputManager)
    deps.output_manager.resolve_correlated_input.return_value = None
    runner = MagicMock()
    runner.workflow_name = "w"
    runner.staged_input_fingerprint.return_value = None
    runner.retried_records = frozenset()
    runner.action_configs = {}
    runner.get_action_folder.return_value = "/tmp/agent_io_absent"
    runner.execution_order = ["split"]
    runner.run_action.return_value = "/output"
    runner.storage_backend = storage
    deps.action_runner = runner
    return ActionExecutor(deps), deps.state_manager


def _storage_with_passthrough() -> MagicMock:
    storage = MagicMock()
    storage.has_disposition.side_effect = (
        lambda _name, disposition, **_: disposition == "passthrough"
    )
    storage.get_failed_items.return_value = []
    storage.get_storage_stats.return_value = {"nodes": {}}
    return storage


def _recorded_completion(state: MagicMock) -> dict:
    completed = [c for c in state.update_status.call_args_list if ActionStatus.COMPLETED in c.args]
    assert completed, "the action was never recorded as completed"
    return completed[-1].kwargs


@pytest.mark.parametrize(
    ("action", "kind", "vendor", "records_time"),
    [
        pytest.param("split", "tool", "tool", True, id="tool_runs_online"),
        pytest.param("split", "hitl", "hitl", True, id="hitl_runs_online"),
        pytest.param("define", "llm", "openai", False, id="llm_takes_the_passthrough_path"),
    ],
)
def test_only_an_online_only_action_under_batch_records_its_execution_time(
    action, kind, vendor, records_time
):
    executor, state = _executor(_storage_with_passthrough())

    with (
        patch("agent_actions.workflow.executor.get_last_usage", return_value=None),
        patch(
            "agent_actions.llm.batch.infrastructure.registry.BatchRegistryManager.has_uncollected_jobs",
            return_value=False,
        ),
    ):
        executor.execute_action_sync(
            action,
            action_idx=0,
            action_config={"kind": kind, "model_vendor": vendor, "run_mode": RunMode.BATCH},
            is_last_action=False,
        )

    assert ("execution_time" in _recorded_completion(state)) is records_time
