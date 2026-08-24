"""A recovery round must not register over a live one.

The registry is keyed `{parent}_{type}_{attempt}`. That is unique while an
attempt counter only ever climbs — but a reprompt budget that renews per repair
round makes attempt 1 recur, and the second round would overwrite the first's
entry. The overwritten batch is still running and still paid for; nothing ever
reads its results.
"""

from unittest.mock import MagicMock

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services import processing_recovery as pr


class _Registry:
    """A registry that remembers, so a collision is visible."""

    def __init__(self):
        self.rows: dict[str, BatchJobEntry] = {}

    def save_batch_job(self, file_name: str, entry: BatchJobEntry) -> None:
        self.rows[file_name] = entry

    def get_all_jobs(self) -> dict[str, BatchJobEntry]:
        return dict(self.rows)


def _register(manager, batch_id: str, kind: RecoveryType, attempt: int) -> None:
    pr.register_recovery_batch(
        manager,
        (batch_id, 1),
        "f.json",
        "openai",
        kind,
        attempt,
        existing=manager.get_all_jobs(),
    )


class TestARenewedRoundGetsItsOwnKey:
    def test_two_rounds_at_the_same_attempt_both_survive(self):
        manager = _Registry()
        _register(manager, "b-1", RecoveryType.REPROMPT, 1)
        _register(manager, "b-2", RecoveryType.REPROMPT, 1)
        ids = sorted(e.batch_id for e in manager.rows.values())
        assert ids == ["b-1", "b-2"], (
            f"one round overwrote the other's entry ({ids}); the loser is still running at the "
            "provider, still paid for, and nothing will ever read it"
        )

    def test_the_original_key_shape_is_kept_for_the_first_round(self):
        """Existing registries and their file names stay readable."""
        manager = _Registry()
        _register(manager, "b-1", RecoveryType.REPROMPT, 1)
        assert "f.json_reprompt_1" in manager.rows

    def test_a_repair_round_and_a_reprompt_round_never_collide(self):
        manager = _Registry()
        _register(manager, "b-1", RecoveryType.REPROMPT, 1)
        _register(manager, "b-2", RecoveryType.REPAIR, 1)
        assert len(manager.rows) == 2

    def test_climbing_attempts_still_get_distinct_keys(self):
        manager = _Registry()
        _register(manager, "b-1", RecoveryType.REPROMPT, 1)
        _register(manager, "b-2", RecoveryType.REPROMPT, 2)
        assert len(manager.rows) == 2


class TestWhatIsRegisteredIsStillCorrect:
    def test_the_entry_describes_its_round(self):
        manager = _Registry()
        _register(manager, "b-1", RecoveryType.REPROMPT, 2)
        entry = next(iter(manager.rows.values()))
        assert entry.batch_id == "b-1"
        assert entry.parent_file_name == "f.json"
        assert entry.recovery_type == RecoveryType.REPROMPT
        assert entry.recovery_attempt == 2
        assert entry.status == BatchStatus.SUBMITTED

    def test_it_works_without_being_told_what_exists(self):
        """The caller may not have the registry to hand."""
        manager = MagicMock()
        pr.register_recovery_batch(
            manager, ("b-1", 1), "f.json", "openai", RecoveryType.REPROMPT, 1
        )
        manager.save_batch_job.assert_called_once()
