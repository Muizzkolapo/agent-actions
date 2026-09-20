"""A limit that could not have dropped a record must not re-run the action (610).

The completion stamp records the limit in force, not what it did. Comparing
limits alone cannot tell a limit that truncated from one too large to have
touched anything, so raising or lifting a limit that never bit resets a
completed action, clears its per-record dispositions — including `failed` and
`exhausted` rows for records the new run never touches — and re-generates every
record at provider cost.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.utils.limits import record_indices_to_process
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus


class _Backend:
    """A weak-referenceable stand-in; the observation registry keys on identity."""


def _records(count: int) -> list[dict[str, str]]:
    return [{"source_guid": f"g{i}"} for i in range(count)]


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)


@pytest.fixture
def executor():
    deps = MagicMock(spec=ExecutorDependencies)
    deps.state_manager = MagicMock(spec=ActionStateManager)
    deps.action_runner = MagicMock()
    deps.action_runner.retried_records = frozenset()
    return ActionExecutor(deps)


def _stamp(**overrides):
    details = {"record_limit": None, "file_limit": None}
    details.update(overrides)
    return details


class TestTheStampCarriesTheOutcome:
    """The stamp has to answer "could the record set differ now", which takes
    what the slice saw — the only place that knows whether anything was dropped."""

    def test_it_records_the_count_a_run_with_no_limit_saw(self, executor):
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process(_records(6), {}, "act", storage_backend=backend)

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] == 6
        assert stamp["truncated"] is False

    def test_a_limit_too_large_to_bite_stamps_not_truncated(self, executor):
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process(
            _records(6), {"record_limit": 1000}, "act", storage_backend=backend
        )

        stamp = executor._completion_metadata("act", {"record_limit": 1000})

        assert stamp["records_processed"] == 6
        assert stamp["truncated"] is False

    def test_a_limit_that_dropped_records_stamps_truncated(self, executor):
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process(_records(6), {"record_limit": 2}, "act", storage_backend=backend)

        stamp = executor._completion_metadata("act", {"record_limit": 2})

        assert stamp["records_processed"] == 2
        assert stamp["truncated"] is True

    def test_counts_accumulate_across_the_files_of_one_action(self, executor):
        """The limit applies per file, so a later limit at or above the total
        cannot truncate any single file — summing is the conservative reading."""
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        for _ in range(3):
            record_indices_to_process(_records(2), {}, "act", storage_backend=backend)

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] == 6
        assert stamp["truncated"] is False

    def test_one_uncountable_chunk_makes_the_whole_action_unknown(self, executor):
        """Dropping it from the sum instead would under-count, and an under-count
        is the one error that reads as 'a smaller limit is safe' and skips."""
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process(_records(4), {}, "act", storage_backend=backend)
        record_indices_to_process("not a list", {}, "act", storage_backend=backend)

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] is None

    def test_an_uncountable_chunk_poisons_the_files_after_it_too(self, executor):
        """Order must not matter: once unknown, a later countable chunk cannot
        restore a total that is missing a file's worth of records."""
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process("not a list", {}, "act", storage_backend=backend)
        record_indices_to_process(_records(4), {}, "act", storage_backend=backend)

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] is None

    def test_a_repair_leaves_the_stored_count_where_it_found_it(self, executor):
        """A repair processes the records it names and no others. Storing its
        count would leave a smaller number than the action actually processed,
        and the next run would read a limit above that as one which cannot
        truncate — skipping an action it would in fact cut down."""
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        executor.deps.action_runner.retried_records = frozenset({"g1"})
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            records_processed=6, truncated=False
        )
        record_indices_to_process(
            _records(1), {}, "act", retried=frozenset({"g1"}), storage_backend=backend
        )

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] == 6
        assert stamp["truncated"] is False

    def test_actions_are_counted_separately(self, executor):
        backend = _Backend()
        executor.deps.action_runner.storage_backend = backend
        record_indices_to_process(_records(6), {}, "act", storage_backend=backend)
        record_indices_to_process(_records(2), {}, "other", storage_backend=backend)

        assert executor._completion_metadata("act", {})["records_processed"] == 6
        assert executor._completion_metadata("other", {})["records_processed"] == 2

    def test_an_unobserved_action_stamps_unknown(self, executor):
        """A WHERE-skipped action never slices, so it has nothing to report."""
        executor.deps.action_runner.storage_backend = _Backend()

        stamp = executor._completion_metadata("act", {})

        assert stamp["records_processed"] is None
        assert stamp["truncated"] is None


class TestALimitThatCouldNotHaveDroppedAnything:
    """The cases 610 names, each against a stamp that can say what happened."""

    def test_a_limit_larger_than_the_input_leaves_it_completed(self, monkeypatch, executor):
        """The headline: 1000 against an input of 6 drops nothing."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        storage = MagicMock()
        executor.deps.action_runner.storage_backend = storage
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.COMPLETED
        storage.clear_disposition.assert_not_called()

    def test_a_limit_below_what_it_processed_re_runs_it(self, monkeypatch, executor):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "3")
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING

    def test_a_limit_exactly_the_count_it_processed_leaves_it_completed(
        self, monkeypatch, executor
    ):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "6")
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.COMPLETED

    def test_lifting_a_limit_that_truncated_re_runs_it(self, executor):
        """It saw only part of the input, so removing the limit changes the set."""
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            record_limit=2, records_processed=2, truncated=True
        )

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING

    def test_lifting_a_limit_that_did_not_truncate_leaves_it_completed(self, executor):
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            record_limit=10, records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.COMPLETED

    def test_raising_a_configured_limit_that_never_bit_leaves_it_completed(self, executor):
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            record_limit=100, records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status(
            "act", {"record_limit": 200}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.COMPLETED

    def test_a_stamp_that_cannot_say_keeps_the_coarse_behaviour(self, monkeypatch, executor):
        """Grandfathering: unknown must re-run, or 609's silent skip returns."""
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        executor.deps.state_manager.get_status_details.return_value = _stamp()

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING

    def test_a_truncated_stamp_without_a_count_keeps_the_coarse_behaviour(
        self, monkeypatch, executor
    ):
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1000")
        executor.deps.state_manager.get_status_details.return_value = _stamp(truncated=False)

        status = executor._maybe_invalidate_completed_status("act", {}, ActionStatus.COMPLETED)

        assert status == ActionStatus.PENDING

    def test_a_changed_file_limit_still_invalidates(self, executor):
        """Precision about the record limit does not loosen the file_limit term,
        which has no count to reason from."""
        executor.deps.state_manager.get_status_details.return_value = _stamp(
            file_limit=2, records_processed=6, truncated=False
        )

        status = executor._maybe_invalidate_completed_status(
            "act", {"file_limit": 5}, ActionStatus.COMPLETED
        )

        assert status == ActionStatus.PENDING
