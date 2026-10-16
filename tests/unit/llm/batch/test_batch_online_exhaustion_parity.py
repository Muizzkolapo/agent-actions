"""What ships when the loop runs out must not depend on the run mode.

Online routes an exhausted response that cannot hold a verdict to the tombstone
channel: `response=None, executed=False`, with the expectation metadata kept.
Batch shipped the same response as a success carrying no `expect` block at all,
so a downstream `guard: X.expect.overall_pass == true` sees a record with no
verdict rather than a record that failed.
"""

from typing import Any

from agent_actions.llm.batch.services.repair_ops import (
    apply_exhaustion_policy,
    build_repair_strategy,
    stamp_exhausted,
)
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "author"
PASSING = {"options": ["a", "b"]}
FAILING = {"options": ["only-one"]}


def _agent_config(on_exhausted: str = "return_last") -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "expect": {
            "repair": "auto",
            "max_iterations": 2,
            "on_exhausted": on_exhausted,
            "expectations": [
                {"id": "enough", "type": "item_count", "field": "options", "params": {"min": 2}}
            ],
        },
    }


def _exhaust(content: Any, on_exhausted: str = "return_last") -> BatchResult:
    strategy = build_repair_strategy(_agent_config(on_exhausted))
    result = BatchResult(custom_id="r1", content=content, success=True)
    strategy.evaluate(result)
    strategy.write_verdicts([result])
    stamp_exhausted([result], strategy, attempts=2)
    apply_exhaustion_policy([result], strategy, ACTION)
    return result


class TestAResponseThatCannotCarryAVerdictIsTombstoned:
    def test_a_bare_string_does_not_ship_as_a_success(self):
        result = _exhaust("I cannot answer that.")
        assert result.success is False, (
            "a response with nowhere to put a verdict shipped as a success; a downstream guard on "
            "expect.overall_pass reads a record with no verdict rather than one that failed"
        )

    def test_its_content_is_cleared_like_online_does(self):
        result = _exhaust("I cannot answer that.")
        assert result.content is None

    def test_the_reason_it_failed_is_kept(self):
        result = _exhaust("I cannot answer that.")
        expectations = result.recovery_metadata.expectations
        assert expectations.attempts == 2
        assert expectations.failed == ["_structural"]

    def test_a_list_of_non_records_is_tombstoned_too(self):
        result = _exhaust(["just", "strings"])
        assert result.success is False
        assert result.content is None


class TestARecordThatCanCarryAVerdictStillShips:
    def test_return_last_keeps_the_annotated_record(self):
        result = _exhaust(dict(FAILING))
        assert result.success is True
        assert result.content["options"] == ["only-one"]
        assert result.content["expect"]["overall_pass"] is False

    def test_an_expansion_of_records_still_ships(self):
        result = _exhaust([dict(PASSING), dict(FAILING)])
        assert result.success is True
        assert result.content[0]["expect"]["overall_pass"] is True
        assert result.content[1]["expect"]["overall_pass"] is False

    def test_a_provider_failure_keeps_its_own_error(self):
        strategy = build_repair_strategy(_agent_config("fail"))
        result = BatchResult(custom_id="r1", content=None, success=False, error="429 rate limited")
        stamp_exhausted([result], strategy, attempts=2)
        apply_exhaustion_policy([result], strategy, ACTION)
        assert "429 rate limited" in (result.error or "")


class TestWhichResultsReadAsExhausted:
    """The mark that makes a batch record read `exhausted`, as online's does."""

    def test_a_record_the_fail_policy_gave_up_on_is_marked(self):
        result = _exhaust(dict(FAILING), "fail")
        assert result.success is False
        assert result.exhausted is True

    def test_a_response_with_nowhere_for_a_verdict_is_marked_under_every_policy(self):
        assert _exhaust("I cannot answer that.", "return_last").exhausted is True
        assert _exhaust("I cannot answer that.", "fail").exhausted is True

    def test_return_last_keeps_a_carryable_record_as_the_success_it_ships_as(self):
        result = _exhaust(dict(FAILING), "return_last")
        assert result.success is True
        assert result.exhausted is False

    def test_a_provider_failure_stays_a_failure_not_an_exhaustion(self):
        strategy = build_repair_strategy(_agent_config("fail"))
        result = BatchResult(custom_id="r1", content=None, success=False, error="429 rate limited")
        stamp_exhausted([result], strategy, attempts=2)
        apply_exhaustion_policy([result], strategy, ACTION)
        assert result.exhausted is False


class TestOnExhaustedRaise:
    """`raise` halts the run, and the records it stopped at are not answers."""

    def _apply(self, content: Any, error: str | None = None):
        strategy = build_repair_strategy(_agent_config("raise"))
        result = BatchResult(custom_id="r1", content=content, success=error is None, error=error)
        strategy.evaluate(result)
        strategy.write_verdicts([result])
        stamp_exhausted([result], strategy, attempts=2)
        return result, apply_exhaustion_policy([result], strategy, ACTION)

    def test_the_halt_it_returns_is_tagged_as_one(self):
        from agent_actions.errors import raised_by_exhaustion_policy

        _, halt = self._apply(dict(FAILING))

        assert halt is not None
        assert raised_by_exhaustion_policy(halt)

    def test_the_record_it_stopped_at_is_exhausted_not_a_success(self):
        result, _ = self._apply(dict(FAILING))

        assert result.success is False
        assert result.exhausted is True

    def test_a_provider_failure_is_still_not_an_exhaustion(self):
        result, halt = self._apply(None, error="429 rate limited")

        assert result.exhausted is False
        assert "429 rate limited" in (result.error or "")
        assert halt is not None


def test_an_online_exhaustion_halt_is_tagged_as_one():
    from agent_actions.errors import raised_by_exhaustion_policy
    from agent_actions.expectations.service import ExpectationsExhaustedError

    assert raised_by_exhaustion_policy(ExpectationsExhaustedError("act", ["rule"], 2))
