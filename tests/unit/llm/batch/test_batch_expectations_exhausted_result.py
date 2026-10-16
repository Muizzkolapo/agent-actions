"""A record the expectation loop gave up on reaches the batch output as online's exhausted one.

Online builds an `expectations_exhausted` tombstone and an EXHAUSTED result; batch used to hand
the same record to the failure path. These push results through `BatchResultStrategy` after the
exhaustion policy has marked them, as the finaliser does.
"""

from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.repair_ops import (
    apply_exhaustion_policy,
    build_repair_strategy,
    stamp_exhausted,
)
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import ProcessingStatus
from agent_actions.record.reasons import EXPECTATIONS_EXHAUSTED

ACTION = "author"
FAILING = {"options": ["only-one"]}


def _agent_config(on_exhausted: str) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "json_mode": True,
        "expect": {
            "repair": "auto",
            "max_iterations": 2,
            "on_exhausted": on_exhausted,
            "expectations": [
                {"id": "enough", "type": "item_count", "field": "options", "params": {"min": 2}}
            ],
        },
    }


def _give_up(content: Any, on_exhausted: str, error: str | None = None) -> list:
    """The results the strategy yields for two records, the first given up on."""
    config = _agent_config(on_exhausted)
    strategy = build_repair_strategy(config)
    first = BatchResult(custom_id="r1", content=content, success=error is None, error=error)
    strategy.evaluate(first)
    strategy.write_verdicts([first])
    stamp_exhausted([first], strategy, attempts=2)
    apply_exhaustion_policy([first], strategy, ACTION)
    context_map = {
        cid: {
            "target_id": cid,
            "source_guid": f"sg-{cid}",
            "content": {"source": {"t": cid}},
            "lineage": ["upstream-node"],
        }
        for cid in ("r1", "r2")
    }
    other = BatchResult(custom_id="r2", content={"options": ["a", "b"]}, success=True)
    return BatchResultStrategy().process(
        [first, other], context_map=context_map, output_directory="/tmp/x", agent_config=config
    )


def _for(results: list, source_guid: str):
    (match,) = [r for r in results if r.source_guid == source_guid]
    return match


@pytest.mark.parametrize(
    ("content", "on_exhausted"),
    [(dict(FAILING), "fail"), ("I cannot answer that.", "return_last"), ("no", "fail")],
)
def test_a_record_given_up_on_is_an_exhausted_result(content, on_exhausted):
    result = _for(_give_up(content, on_exhausted), "sg-r1")

    assert result.status == ProcessingStatus.EXHAUSTED
    assert result.data[0]["_tombstone_reason"] == EXPECTATIONS_EXHAUSTED
    assert "Expectations exhausted after 2 iteration(s)" in (result.error or "")


def test_it_is_the_only_result_for_the_record():
    results = _give_up(dict(FAILING), "fail")

    assert [r.source_guid for r in results].count("sg-r1") == 1


def test_it_carries_the_context_its_lineage_is_built_from():
    result = _for(_give_up(dict(FAILING), "fail"), "sg-r1")

    assert result.processing_context is not None
    assert result.input_record["lineage"] == ["upstream-node"]


def test_the_expectations_it_failed_stay_on_its_recovery_metadata():
    result = _for(_give_up(dict(FAILING), "fail"), "sg-r1")

    assert result.recovery_metadata.expectations.attempts == 2
    assert result.recovery_metadata.expectations.failed == ["enough"]


def test_a_record_that_passed_is_not_exhausted():
    result = _for(_give_up(dict(FAILING), "fail"), "sg-r2")

    assert result.status == ProcessingStatus.SUCCESS


def test_a_provider_failure_stays_failed_not_exhausted():
    result = _for(_give_up(None, "fail", error="429 rate limited"), "sg-r1")

    assert result.status == ProcessingStatus.FAILED
    assert "429 rate limited" in (result.error or "")
