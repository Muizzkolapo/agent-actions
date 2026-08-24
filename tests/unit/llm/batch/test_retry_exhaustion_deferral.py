"""`retry: on_exhausted: raise` must not take the file's other records with it.

Batch writes its output once, at the end. The retry policy raised from inside
the conversion step, which runs before that write — so halting discarded every
record in the file that had converted cleanly, each of which was already paid
for. This is the same shape as the expectations policy, which defers its raise
until the file is on disk.
"""

from typing import Any

from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

ACTION = "author"


def _agent_config(on_exhausted: str) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "json_mode": True,
        "model_name": "test-model",
        "run_mode": "batch",
        "retry": {"max_attempts": 2, "on_exhausted": on_exhausted},
    }


def _context_map() -> dict[str, Any]:
    return {
        cid: {"target_id": cid, "source_guid": f"sg-{cid}", "content": {"source": {"t": cid}}}
        for cid in ("paid-for", "gone")
    }


def _convert(on_exhausted: str):
    """Convert a file where one record came back and one never did.

    A record the provider never returned is reconciled as a passthrough; that is
    where the retry policy is consulted.
    """
    strategy = BatchResultStrategy()
    returned = [BatchResult(custom_id="paid-for", content={"answer": "kept"}, success=True)]
    exhausted = {
        "gone": RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=2, succeeded=False, reason="api_error")
        )
    }
    return strategy, strategy.process(
        batch_results=returned,
        context_map=_context_map(),
        output_directory="/tmp/test",
        agent_config=_agent_config(on_exhausted),
        exhausted_recovery=exhausted,
    )


def _target_ids(processed) -> list[str]:
    return [row.get("target_id") for r in processed for row in (r.data or [])]


class TestRaiseDoesNotDiscardTheRestOfTheFile:
    def test_the_conversion_completes(self):
        _strategy, processed = _convert("raise")
        assert processed is not None, (
            "conversion raised, so the caller never reached the write and every record in this "
            "file was lost — including the one that succeeded"
        )

    def test_the_record_that_succeeded_is_still_there(self):
        _strategy, processed = _convert("raise")
        ids = _target_ids(processed)
        assert "paid-for" in ids, f"the surviving record is missing from {ids}"

    def test_the_halt_is_handed_back_instead(self):
        strategy, _processed = _convert("raise")
        pending = strategy.pending_exhaustion
        assert isinstance(pending, RuntimeError)
        assert "gone" in str(pending)
        assert "on_exhausted=raise" in str(pending)

    def test_the_exhausted_record_still_carries_its_failure(self):
        _strategy, processed = _convert("raise")
        gone = [r for r in processed if r.source_guid == "sg-gone"]
        assert gone, "the exhausted record must still reach the output as a tombstone"


class TestTheOtherPoliciesAreUnchanged:
    def test_return_last_hands_back_nothing(self):
        strategy, processed = _convert("return_last")
        assert strategy.pending_exhaustion is None
        assert len(processed) == 2

    def test_a_run_with_no_exhausted_records_hands_back_nothing(self):
        strategy = BatchResultStrategy()
        strategy.process(
            batch_results=[BatchResult(custom_id="paid-for", content={"a": 1}, success=True)],
            context_map=_context_map(),
            output_directory="/tmp/test",
            agent_config=_agent_config("raise"),
            exhausted_recovery=None,
        )
        assert strategy.pending_exhaustion is None

    def test_a_later_clean_conversion_clears_the_previous_halt(self):
        """The strategy instance is reused, so a stale halt must not leak."""
        strategy, _ = _convert("raise")
        assert strategy.pending_exhaustion is not None
        strategy.process(
            batch_results=[BatchResult(custom_id="paid-for", content={"a": 1}, success=True)],
            context_map=_context_map(),
            output_directory="/tmp/test",
            agent_config=_agent_config("raise"),
            exhausted_recovery=None,
        )
        assert strategy.pending_exhaustion is None, (
            "a halt from an earlier file would stop a later, healthy one"
        )
