"""An `expect:` block must behave the same in batch as it does online.

Swapping `run_mode: online` for `run_mode: batch` is documented as a one-line
environment change, so a config carrying expectations has to work on both paths
or the promise is broken. These tests pin the verdict a batch record receives
against the verdict the online path produces for the same record and the same
suite.
"""

from typing import Any

from agent_actions.expectations.service import (
    ExpectationService,
    create_expectation_service_from_config,
)
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "assess"

EXPECT_BLOCK: dict[str, Any] = {
    "repair": "none",
    "expectations": [
        {
            "id": "density_known",
            "type": "accepted_values",
            "field": "density",
            "params": {"values": ["high", "low"]},
        },
        {"id": "reason_present", "type": "not_null", "field": "reason"},
    ],
}

PASSING = {"density": "high", "reason": "covers the material in depth"}
FAILING = {"density": "VERY HIGH", "reason": "covers the material in depth"}


def _agent_config(expect: dict[str, Any] | None = EXPECT_BLOCK) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": ACTION,
        "action_name": ACTION,
        "json_mode": True,
        "run_mode": "batch",
    }
    if expect is not None:
        config["expect"] = expect
    return config


def _run_batch(content: Any, expect: dict[str, Any] | None = EXPECT_BLOCK):
    """Push one provider result through BatchResultStrategy; return its records."""
    custom_id = "t-001"
    original_row = {"target_id": custom_id, "source_guid": "sg-001", "content": {}}
    batch_result = BatchResult(custom_id=custom_id, content=content, success=True)
    ctx = BatchProcessingContext(
        batch_results=[batch_result],
        context_map={custom_id: original_row},
        output_directory="/tmp/test",
        agent_config=_agent_config(expect),
    )
    ctx.reconciler = BatchResultReconciler(context_map=ctx.context_map)
    result = BatchResultStrategy()._process_successful_result(ctx, batch_result, custom_id)
    return result.data


def _online_verdict(record: dict[str, Any]) -> dict[str, Any]:
    """The verdict the online path would attach to the same record."""
    service = create_expectation_service_from_config(
        EXPECT_BLOCK, action_name=ACTION, agent_config=_agent_config()
    )
    run = service.execute(lambda prompt: ([record], True), "PROMPT")
    return run.suite_result.to_record_dict()


class TestBatchAttachesTheVerdict:
    def test_a_batch_record_carries_the_verdict(self):
        records = _run_batch(PASSING)
        assert records, "batch produced no record"
        namespace = records[0]["content"][ACTION]
        assert "expect" in namespace, "batch dropped the verdict the online path attaches"
        assert namespace["expect"]["overall_pass"] is True

    def test_a_failing_batch_record_carries_the_failure(self):
        namespace = _run_batch(FAILING)[0]["content"][ACTION]
        assert namespace["expect"]["overall_pass"] is False
        assert namespace["expect"]["failed"] == ["density_known"]

    def test_the_record_fields_survive_the_attachment(self):
        namespace = _run_batch(PASSING)[0]["content"][ACTION]
        assert namespace["density"] == "high"
        assert namespace["reason"] == "covers the material in depth"

    def test_no_verdict_when_the_action_has_no_expect_block(self):
        namespace = _run_batch(PASSING, expect=None)[0]["content"][ACTION]
        assert "expect" not in namespace


class TestVerdictParityWithOnline:
    def test_a_passing_record_gets_an_identical_verdict_in_both_modes(self):
        batch = _run_batch(PASSING)[0]["content"][ACTION]["expect"]
        assert batch == _online_verdict(PASSING)

    def test_a_failing_record_gets_an_identical_verdict_in_both_modes(self):
        batch = _run_batch(FAILING)[0]["content"][ACTION]["expect"]
        assert batch == _online_verdict(FAILING)


class TestExpansionRecords:
    def test_every_record_of_a_fan_out_is_validated_independently(self):
        records = _run_batch([PASSING, FAILING])
        assert len(records) == 2, "a two-item response must produce two records"
        verdicts = [r["content"][ACTION]["expect"]["overall_pass"] for r in records]
        assert verdicts == [True, False]


class TestJudgeBudgetIsSharedAcrossTheBatch:
    def test_one_service_serves_every_record_in_the_batch(self):
        """The budget is per action per run, so the batch must not rebuild it per record."""
        custom_ids = ["t-001", "t-002"]
        context_map = {
            cid: {"target_id": cid, "source_guid": f"sg-{cid}", "content": {}} for cid in custom_ids
        }
        batch_results = [
            BatchResult(custom_id=cid, content=PASSING, success=True) for cid in custom_ids
        ]
        ctx = BatchProcessingContext(
            batch_results=batch_results,
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config=_agent_config(),
        )
        ctx.reconciler = BatchResultReconciler(context_map=context_map)
        strategy = BatchResultStrategy()
        first = strategy._expectation_service(ctx)
        second = strategy._expectation_service(ctx)
        assert first is second, "the service must be built once and reused across the batch"
        assert isinstance(first, ExpectationService)


class TestServiceIsScopedToTheAction:
    """One BatchResultStrategy is built per workflow and reused for every batch
    action, so the expectation service must be scoped to the action being
    processed — never cached on the strategy itself."""

    @staticmethod
    def _ctx_for(action: str, expect: dict[str, Any]) -> BatchProcessingContext:
        custom_id = "t-001"
        row = {"target_id": custom_id, "source_guid": "sg-001", "content": {}}
        ctx = BatchProcessingContext(
            batch_results=[BatchResult(custom_id=custom_id, content=PASSING, success=True)],
            context_map={custom_id: row},
            output_directory="/tmp/test",
            agent_config={
                "name": action,
                "action_name": action,
                "json_mode": True,
                "run_mode": "batch",
                "expect": expect,
            },
        )
        ctx.reconciler = BatchResultReconciler(context_map=ctx.context_map)
        return ctx

    def test_a_second_action_does_not_inherit_the_first_actions_suite(self):
        other_expect = {
            "repair": "none",
            "expectations": [{"id": "other_rule", "type": "not_null", "field": "density"}],
        }
        strategy = BatchResultStrategy()
        first = strategy._expectation_service(self._ctx_for("assess", EXPECT_BLOCK))
        second = strategy._expectation_service(self._ctx_for("classify", other_expect))

        assert first is not second, "the second action got the first action's service"
        assert [e.resolved_id for e in second.suite.expectations] == ["other_rule"]

    def test_an_action_without_expectations_does_not_inherit_a_suite(self):
        strategy = BatchResultStrategy()
        strategy._expectation_service(self._ctx_for("assess", EXPECT_BLOCK))
        ctx = self._ctx_for("plain", EXPECT_BLOCK)
        ctx.agent_config.pop("expect")
        assert strategy._expectation_service(ctx) is None

    def test_the_service_is_still_reused_within_one_action(self):
        strategy = BatchResultStrategy()
        ctx = self._ctx_for("assess", EXPECT_BLOCK)
        assert strategy._expectation_service(ctx) is strategy._expectation_service(ctx)


class TestConfigErrorsAreNotDowngraded:
    def test_a_config_error_is_fatal_rather_than_a_per_record_failure(self):
        """A bad expect: block must stop the action, not quietly fail every record."""
        import pytest

        from agent_actions.errors import ConfigurationError

        custom_id = "t-001"
        row = {"target_id": custom_id, "source_guid": "sg-001", "content": {}}
        agent_config = {
            "name": ACTION,
            "action_name": ACTION,
            "json_mode": True,
            "run_mode": "batch",
            # A named suite cannot be resolved without project root/workflow.
            "expect": {"repair": "none", "suite": "some_suite"},
        }
        with pytest.raises(ConfigurationError):
            BatchResultStrategy().process(
                [BatchResult(custom_id=custom_id, content=PASSING, success=True)],
                context_map={custom_id: row},
                output_directory="/tmp/test",
                agent_config=agent_config,
            )

    def test_the_assembler_does_not_re_judge_a_record_the_repair_loop_already_judged(self):
        """Under a repair policy the verdict is written by the loop, not here.

        Re-running the suite would spend the judge budget a second time on
        content it has already judged, and could reach a different verdict from
        the one the loop acted on.
        """
        custom_id = "t-001"
        row = {"target_id": custom_id, "source_guid": "sg-001", "content": {}}
        agent_config = {
            "name": ACTION,
            "action_name": ACTION,
            "json_mode": True,
            "run_mode": "batch",
            "expect": {"repair": "auto", "expectations": EXPECT_BLOCK["expectations"]},
        }
        results = BatchResultStrategy().process(
            [BatchResult(custom_id=custom_id, content=PASSING, success=True)],
            context_map={custom_id: row},
            output_directory="/tmp/test",
            agent_config=agent_config,
        )
        content = results[0].data[0]["content"][ACTION]
        assert "expect" not in content
