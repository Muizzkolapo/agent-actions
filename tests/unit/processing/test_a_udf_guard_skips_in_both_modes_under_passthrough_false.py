"""A UDF guard that raises skips the record in both modes under passthrough_on_error: false (1315).

`TaskPreparer.judge` (batch) and `.prepare` (online) both reach `_evaluate_guard`,
which now threads `conditional_clause_passthrough_on_error` from the expanded
config through to the evaluator, so a raising UDF guard is skipped in either
mode instead of silently passing every time.
"""

from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.utils.udf_management import registry as registry_module
from agent_actions.utils.udf_management.registry import UDF_REGISTRY


def _context(passthrough_on_error: bool) -> PreparationContext:
    config = {
        "granularity": "record",
        "context_scope": {"observe": ["a1.n"]},
        "prompt": "Say {{ a1.n }}.",
        "json_mode": False,
        "conditional_clause": "guard_udf_raises_for_1315",
        "conditional_clause_passthrough_on_error": passthrough_on_error,
    }
    return PreparationContext(
        agent_config=config, agent_name="a2", agent_indices={"a1": 0, "a2": 1}
    )


def _record() -> dict:
    return {"source_guid": "G0", "content": {"a1": {"n": 1}}}


def guard_udf_raises_for_1315(data):
    raise RuntimeError("boom")


def test_both_modes_skip_when_passthrough_on_error_is_false():
    modules_before = set(registry_module._registered_modules)
    registry_module.udf_tool(guard_udf_raises_for_1315)
    try:
        context = _context(passthrough_on_error=False)
        assert TaskPreparer().judge(_record(), context) == GuardStatus.SKIPPED
        assert TaskPreparer().prepare(_record(), context).guard_status == GuardStatus.SKIPPED
    finally:
        UDF_REGISTRY.pop("guard_udf_raises_for_1315", None)
        registry_module._registered_modules.intersection_update(modules_before)


def test_both_modes_still_pass_when_passthrough_on_error_is_true():
    modules_before = set(registry_module._registered_modules)
    registry_module.udf_tool(guard_udf_raises_for_1315)
    try:
        context = _context(passthrough_on_error=True)
        assert TaskPreparer().judge(_record(), context) == GuardStatus.PASSED
        assert TaskPreparer().prepare(_record(), context).guard_status == GuardStatus.PASSED
    finally:
        UDF_REGISTRY.pop("guard_udf_raises_for_1315", None)
        registry_module._registered_modules.intersection_update(modules_before)
