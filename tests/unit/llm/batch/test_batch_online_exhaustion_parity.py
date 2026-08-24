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
            "expectations": [{"id": "enough", "type": "item_count", "field": "options", "min": 2}],
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
