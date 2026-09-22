"""The workflow's own `storage:` block, and the rule that let it be missed.

`coordinator.py` reads this key straight off the raw workflow dict, through a
`getattr(config_mgr, "user_config", None)` — a shape a grep for `user_config.get`
does not find. A surface that forbids undeclared keys has to declare every key the
framework itself goes looking for, however it reaches them.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import WorkflowConfig

VALID = {
    "name": "w",
    "description": "d",
    "actions": [{"name": "a", "intent": "i"}],
}


class TestTheStorageBlockLoads:
    def test_a_workflow_configuring_trace_retention_still_loads(self):
        """The knob `storage/ARCHITECTURE.md` documents as a user config key."""
        workflow = WorkflowConfig.model_validate(
            {**VALID, "storage": {"prompt_trace_retention_runs": 3}}
        )

        assert workflow.storage is not None
        assert workflow.storage.prompt_trace_retention_runs == 3

    def test_both_knobs_the_coordinator_reads_are_declared(self):
        """Asserted together: the coordinator asks for both in one call, so a
        block carrying both is the shape that actually reaches it."""
        workflow = WorkflowConfig.model_validate(
            {**VALID, "storage": {"prompt_trace_retention_runs": 3, "source_data_ttl_days": 7}}
        )

        assert (
            workflow.storage.prompt_trace_retention_runs,
            workflow.storage.source_data_ttl_days,
        ) == (3, 7)

    def test_it_defaults_to_none_so_the_coordinator_keeps_its_own_defaults(self):
        assert WorkflowConfig.model_validate(VALID).storage is None


class TestTheStorageBlockIsGuardedLikeDefaults:
    """Declaring the block as an open dict would have re-created the bug this
    change exists to close, one level down."""

    def test_a_misspelled_knob_is_refused_with_the_near_match(self):
        with pytest.raises(ValidationError) as excinfo:
            WorkflowConfig.model_validate({**VALID, "storage": {"prompt_trace_retention_run": 3}})

        assert (
            "unknown storage key 'prompt_trace_retention_run' — "
            "did you mean 'prompt_trace_retention_runs'?"
            in "; ".join(e["msg"] for e in excinfo.value.errors())
        )

    def test_a_retention_of_zero_is_refused(self):
        """Keeping zero days of traces is deleting all of them; a config that
        means 'do not prune' omits the key."""
        with pytest.raises(ValidationError):
            WorkflowConfig.model_validate({**VALID, "storage": {"source_data_ttl_days": 0}})
