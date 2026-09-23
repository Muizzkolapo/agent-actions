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

    def test_zero_is_accepted_because_it_is_the_backend_s_own_disable_value(self):
        """`_enforce_prompt_trace_retention` opens `if retention_runs < 1: return`,
        so zero prunes nothing. Omitting the key is not the same thing — the
        default is 10 days and prunes — so zero is the only way to say keep
        everything, and a schema that refused it would take that away."""
        workflow = WorkflowConfig.model_validate(
            {**VALID, "storage": {"prompt_trace_retention_runs": 0, "source_data_ttl_days": 0}}
        )

        assert (
            workflow.storage.prompt_trace_retention_runs,
            workflow.storage.source_data_ttl_days,
        ) == (0, 0)

    def test_a_negative_retention_is_refused(self):
        """Below zero says nothing the backend does not already read from zero."""
        with pytest.raises(ValidationError):
            WorkflowConfig.model_validate({**VALID, "storage": {"source_data_ttl_days": -1}})

    def test_a_block_written_with_no_value_is_refused(self):
        """`storage:` with the setting commented out is None, not an empty mapping,
        and the consumer's `get("storage", {})` returns that None rather than the
        default — then calls `.get` on it. The refusal one level down tells a user
        to omit the key, which is exactly how they arrive here."""
        import yaml

        doc = yaml.safe_load("storage:\n  # prompt_trace_retention_runs: 5\n")

        with pytest.raises(ValidationError) as excinfo:
            WorkflowConfig.model_validate({**VALID, **doc})

        assert "workflow key 'storage' is present with no value" in "; ".join(
            e["msg"] for e in excinfo.value.errors()
        )

    @pytest.mark.parametrize("value", ["10", True, 1.5], ids=["quoted int", "bool", "float"])
    def test_a_value_the_consumer_would_receive_unconverted_is_refused(self, value):
        """These fields are strict because the consumer reads the raw dict. Coercing
        `"10"` to 10 here would convert only this copy, and hand the backend the
        string — where `retention_runs < 1` raises TypeError. `true` is worse: it
        converts to 1 and prunes to a single day, silently."""
        with pytest.raises(ValidationError):
            WorkflowConfig.model_validate(
                {**VALID, "storage": {"prompt_trace_retention_runs": value}}
            )

    @pytest.mark.parametrize("key", ["prompt_trace_retention_runs", "source_data_ttl_days"])
    def test_a_key_present_with_no_value_is_refused(self, key):
        """The consumer reads the raw dict — `storage_config.get(key, DEFAULT)` —
        so a key written with no value beats the default and arrives as None,
        where `retention_runs < 1` raises TypeError inside the maintenance call
        and a run that completed every action is reported as failed. Omitting the
        key is what takes the default."""
        with pytest.raises(ValidationError) as excinfo:
            WorkflowConfig.model_validate({**VALID, "storage": {key: None}})

        assert f"storage key '{key}' is present with no value" in "; ".join(
            e["msg"] for e in excinfo.value.errors()
        )
