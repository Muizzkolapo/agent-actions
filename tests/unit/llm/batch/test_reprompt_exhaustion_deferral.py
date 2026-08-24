"""`reprompt: on_exhausted: raise` must not take the file's other records with it.

The third site with this shape. Batch writes its output once, at the end, so a
policy that throws while stamping exhaustion metadata halts before that write —
discarding every record the reprompt rounds had already graduated, each already
paid for. Online persists per record, so the same policy keeps them.
"""

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation import apply_exhausted_reprompt

VALIDATION = "check_it"


def _results():
    return [
        BatchResult(custom_id="paid-for", content={"answer": "kept"}, success=True),
        BatchResult(custom_id="gone", content={"answer": "bad"}, success=True),
    ]


def _apply(on_exhausted: str):
    results = _results()
    pending = apply_exhausted_reprompt(
        results=results,
        failed_ids={"gone"},
        validation_name=VALIDATION,
        attempt=2,
        on_exhausted=on_exhausted,
    )
    return results, pending


class TestRaiseDoesNotDiscardTheRestOfTheFile:
    def test_the_stamping_completes(self):
        results, _pending = _apply("raise")
        assert results is not None, (
            "stamping raised, so the caller never reached the write and every record in this "
            "file was lost — including the one that passed"
        )

    def test_the_halt_is_handed_back(self):
        _results, pending = _apply("raise")
        assert isinstance(pending, RuntimeError)
        assert "gone" in str(pending)
        assert VALIDATION in str(pending)

    def test_the_record_that_passed_is_untouched(self):
        results, _pending = _apply("raise")
        kept = next(r for r in results if r.custom_id == "paid-for")
        assert kept.success is True
        assert kept.content == {"answer": "kept"}


class TestTheOtherPoliciesAreUnchanged:
    def test_return_last_hands_back_nothing(self):
        results, pending = _apply("return_last")
        assert pending is None
        assert len(results) == 2

    def test_the_exhausted_record_is_still_stamped(self):
        results, _pending = _apply("return_last")
        gone = next(r for r in results if r.custom_id == "gone")
        assert gone.recovery_metadata is not None
        assert gone.recovery_metadata.reprompt is not None

    def test_nothing_failed_means_nothing_to_raise(self):
        results = _results()
        assert (
            apply_exhausted_reprompt(
                results=results,
                failed_ids=set(),
                validation_name=VALIDATION,
                attempt=2,
                on_exhausted="raise",
            )
            is None
        )
