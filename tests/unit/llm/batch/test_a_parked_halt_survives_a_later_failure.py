"""A halt parked while the pass goes on is not lost to a later file's hard failure.

The pass collects every file before it raises a halt. If a later file fails in a way
that ends the pass at once, the halt it parked is still the run's real stop: left
unraised, the action is never marked halted and a rerun can complete it over the
halting file, which is already written and collected.
"""

import pytest

from agent_actions.errors import mark_action_fatal
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.expectations.service import ExpectationConfigurationError
from agent_actions.llm.batch.core.batch_constants import BatchStatus

from .test_pass_finishes_before_halt import _halt, _service


class TestAParkedHaltWinsOverALaterHardFailure:
    @pytest.mark.parametrize(
        "later",
        [
            RuntimeError("provider lost the batch"),
            mark_action_fatal(OSError("the store could not write the file")),
            EmptyOutputError("on_empty: error"),
        ],
        ids=["runtime_error", "action_fatal_store_error", "on_empty_error"],
    )
    def test_the_halt_is_raised_with_the_later_failure_as_its_cause(self, later):
        service, visited = _service(
            ["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": later}
        )

        with pytest.raises(RuntimeError, match="alpha") as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json", "b.json"]
        assert raised.value.__cause__ is later

    def test_an_unresolvable_expect_block_still_wins(self):
        later = ExpectationConfigurationError("bad expect")
        service, _ = _service(["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": later})

        with pytest.raises(ExpectationConfigurationError):
            service.process_all_batch_results("/out", {}, "act")

    def test_a_later_failure_with_no_halt_parked_is_raised_unchanged(self):
        later = RuntimeError("provider lost the batch")
        service, _ = _service(["a.json", "b.json"], {"a.json": "/out/a.json", "b.json": later})

        with pytest.raises(RuntimeError, match="provider lost the batch") as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert raised.value is later


class TestAParkedHaltSurvivesAFailureOutsideAFilesProcessing:
    """Anything that ends the pass, not only an error while one file is processed."""

    def test_a_failure_asking_the_provider_about_a_later_file(self):
        service, visited = _service(
            ["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": "/out/b.json"}
        )
        later = ValueError("the provider answered nonsense")
        service._provider_status.side_effect = [BatchStatus.COMPLETED, later]

        with pytest.raises(RuntimeError, match="alpha") as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json"]
        assert raised.value.__cause__ is later

    def test_a_failure_reading_the_registry_after_the_loop(self):
        service, _ = _service(
            ["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": "/out/b.json"}
        )
        manager = service._registry_manager_factory("act")
        entries = manager.get_all_jobs.return_value
        later = OSError("the registry could not be read")
        manager.get_all_jobs.side_effect = [entries, later]

        with pytest.raises(RuntimeError, match="alpha") as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert raised.value.__cause__ is later

    def test_the_same_failures_with_no_halt_parked_are_raised_unchanged(self):
        service, _ = _service(["a.json"], {"a.json": "/out/a.json"})
        later = ValueError("the provider answered nonsense")
        service._provider_status.side_effect = later

        with pytest.raises(ValueError) as raised:
            service.process_all_batch_results("/out", {}, "act")

        assert raised.value is later
