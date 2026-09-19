"""A run can be told which records it is repairing."""

from __future__ import annotations

from types import SimpleNamespace

from agent_actions.workflow.coordinator import AgentWorkflow


def _workflow_with_runner():
    runner = SimpleNamespace(retried_records=frozenset())
    workflow = AgentWorkflow.__new__(AgentWorkflow)
    workflow.services = SimpleNamespace(core=SimpleNamespace(action_runner=runner))
    return workflow, runner


class TestSetRetriedRecords:
    def test_the_named_records_reach_the_runner(self):
        workflow, runner = _workflow_with_runner()

        workflow.set_retried_records(["a", "b"])

        assert runner.retried_records == frozenset({"a", "b"})

    def test_any_iterable_is_accepted(self):
        workflow, runner = _workflow_with_runner()

        workflow.set_retried_records(iter(["a", "a", "b"]))

        assert runner.retried_records == frozenset({"a", "b"})

    def test_a_run_that_names_nothing_leaves_the_runner_empty(self):
        workflow, runner = _workflow_with_runner()

        workflow.set_retried_records([])

        assert runner.retried_records == frozenset()
