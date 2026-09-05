"""The retry `on_exhausted` policy must stay silent on a healthy result set.

Both directions matter. The policy firing when it should not halts every run
configured `raise`, and nothing else in the suite pins that direction: the
existing "hands back nothing" tests all choose `return_last`, which returns
before the exhaustion predicate is ever consulted.
"""

from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import (
    ProcessingResult,
    RecoveryMetadata,
    RetryMetadata,
)

RAISE = {"retry": {"on_exhausted": "raise"}}


def _succeeded(source_guid: str = "g1") -> ProcessingResult:
    return ProcessingResult.success(data=[{"source_guid": source_guid}], source_guid=source_guid)


def _failed_with_retry(*, succeeded: bool) -> ProcessingResult:
    result = ProcessingResult.failed(error="provider said no", source_guid="g2")
    result.recovery_metadata = RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=2, succeeded=succeeded, reason="missing")
    )
    return result


def _policy(results):
    return ResultCollector._handle_exhausted_policy(
        results=results, agent_config=RAISE, agent_name="a", storage_backend=None
    )


def test_a_clean_result_set_does_not_halt():
    assert _policy([_succeeded()]) is None


def test_a_record_whose_retry_succeeded_does_not_halt():
    assert _policy([_failed_with_retry(succeeded=True)]) is None


def test_a_failure_carrying_no_retry_history_does_not_halt():
    assert _policy([ProcessingResult.failed(error="boom", source_guid="g3")]) is None


def test_a_record_that_spent_its_retries_does_halt():
    halt = _policy([_failed_with_retry(succeeded=False)])
    assert halt is not None
    assert "exhausted" in str(halt).lower()


def test_an_exhausted_record_still_halts():
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted after 2 attempts", data=[{}], source_guid="g4"
    )
    exhausted.recovery_metadata = RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=2, succeeded=False, reason="missing")
    )
    assert _policy([exhausted]) is not None


def test_an_expectations_settled_record_is_left_to_its_own_policy():
    result = _failed_with_retry(succeeded=False)
    from agent_actions.processing.types import ExpectationsMetadata

    result.recovery_metadata.expectations = ExpectationsMetadata(attempts=1, failed=["r"])
    assert _policy([result]) is None


def test_one_spent_record_among_healthy_ones_still_halts():
    """Decided per record: a single spent record is enough, and enough is not all."""
    halt = _policy([_succeeded("a"), _failed_with_retry(succeeded=False), _succeeded("b")])
    assert halt is not None


def test_a_set_where_nothing_spent_its_retries_stays_silent():
    """The mirror — a failure that never retried is not an exhausted one."""
    healthy = [_succeeded("a"), ProcessingResult.failed(error="boom", source_guid="b")]
    assert _policy(healthy) is None
