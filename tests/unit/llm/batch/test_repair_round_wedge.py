"""A repair round that dies at the provider must not stall the file forever.

`check_and_submit_repair` defers when a repair round already owns these records,
so a resume of the never-retired original batch cannot pay for a second
generation of each. The signal was the registry entry's status — but a recovery
entry is written SUBMITTED and only marked COMPLETED inside
`finalize_batch_output`, so it reads as running for the entire life of the file.
A round the provider failed or cancelled therefore deferred every later pass, and
the output was never written at all.

The provider is asked instead: it is the only thing that knows whether a batch
is still running.
"""

from typing import Any
from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services import processing_recovery as pr

FILE = "f.json"


def _round(status_at_provider: str, attempt: int = 1) -> tuple[Any, Any]:
    """A registered repair round, plus the context whose provider reports on it."""
    entry = BatchJobEntry(
        # what register_recovery_batch writes, and never updates
        batch_id=f"b-repair-{attempt}",
        status=BatchStatus.SUBMITTED,
        timestamp="t",
        provider="p",
        file_name=f"{FILE}_repair_{attempt}",
        parent_file_name=FILE,
        recovery_type=RecoveryType.REPAIR,
        recovery_attempt=attempt,
    )
    context = MagicMock()
    context.manager.get_all_jobs.return_value = {entry.file_name: entry}
    context.provider.check_status.return_value = status_at_provider
    return context, MagicMock(file_name=FILE)


class TestADeadRoundDoesNotOwnTheRecordsForever:
    def test_a_failed_round_is_not_in_flight(self):
        context, identity = _round(BatchStatus.FAILED)
        assert pr._repair_round_in_flight(context, identity) is False, (
            "the round failed at the provider and will never return, so every later pass defers "
            "and the file is never written"
        )

    def test_a_cancelled_round_is_not_in_flight(self):
        context, identity = _round(BatchStatus.CANCELLED)
        assert pr._repair_round_in_flight(context, identity) is False

    def test_the_registry_status_is_not_what_is_consulted(self):
        """The entry says SUBMITTED in every one of these cases."""
        context, identity = _round(BatchStatus.FAILED)
        entry = next(iter(context.manager.get_all_jobs.return_value.values()))
        assert entry.status == BatchStatus.SUBMITTED
        assert entry.is_in_flight is True
        assert pr._repair_round_in_flight(context, identity) is False


class TestALiveRoundStillOwnsThem:
    def test_a_running_round_is_in_flight(self):
        context, identity = _round(BatchStatus.IN_PROGRESS)
        assert pr._repair_round_in_flight(context, identity) is True

    def test_a_submitted_round_is_in_flight(self):
        context, identity = _round(BatchStatus.SUBMITTED)
        assert pr._repair_round_in_flight(context, identity) is True

    def test_a_completed_round_still_owns_them_until_it_is_processed(self):
        """Its results have not been folded in yet; another round would duplicate."""
        context, identity = _round(BatchStatus.COMPLETED)
        assert pr._repair_round_in_flight(context, identity) is True


class TestOnlyThisFilesRepairRounds:
    def test_another_file_s_round_is_ignored(self):
        context, identity = _round(BatchStatus.IN_PROGRESS)
        entry = next(iter(context.manager.get_all_jobs.return_value.values()))
        entry.parent_file_name = "other.json"
        assert pr._repair_round_in_flight(context, identity) is False

    def test_no_rounds_at_all(self):
        context, identity = _round(BatchStatus.IN_PROGRESS)
        context.manager.get_all_jobs.return_value = {}
        assert pr._repair_round_in_flight(context, identity) is False
        context.provider.check_status.assert_not_called()
