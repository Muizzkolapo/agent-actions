"""A halt in one file does not leave another file's finished batch uncollected.

`on_exhausted: raise` stops the run, but a sibling file's finished batch still
holds results the provider already answered. Stopping at the first halt strands
them: `agac run` refuses the halted action, and only `--abandon-in-flight`
gets past it, paying again for answers already returned.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.errors.base import exhaustion_halt
from agent_actions.expectations.service import ExpectationConfigurationError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import BatchProcessingService


def _halt(name: str) -> RuntimeError:
    return exhaustion_halt(f"Retry exhausted for {name} (on_exhausted=raise)")


def _entry(name: str) -> BatchJobEntry:
    return BatchJobEntry(
        batch_id=f"b_{name}", status="completed", timestamp="t", provider="mock", file_name=name
    )


def _service(files: list[str], outcomes: dict[str, object]):
    """A service whose per-file processing returns or raises what *outcomes* says."""
    entries = {name: _entry(name) for name in files}
    manager = MagicMock()
    manager.get_all_jobs.return_value = entries
    manager.get_batch_job.side_effect = entries.get
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=lambda name: manager,
        workflow_name="wf",
    )
    service._provider_status = MagicMock(return_value=BatchStatus.COMPLETED)
    service._fail_abandoned_records = MagicMock()
    visited: list[str] = []

    def process(*, file_name, **_kwargs):
        visited.append(file_name)
        outcome = outcomes[file_name]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    service._process_single_batch_file = process
    return service, visited


class TestThePassFinishesBeforeTheHalt:
    def test_a_sibling_after_the_halting_file_is_still_collected(self):
        service, visited = _service(
            ["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": "/out/b.json"}
        )

        with pytest.raises(RuntimeError, match="alpha"):
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json", "b.json"]

    def test_a_halt_on_the_only_file_is_raised_not_masked_by_no_results(self):
        service, _ = _service(["a.json"], {"a.json": _halt("alpha")})

        with pytest.raises(RuntimeError, match="alpha"):
            service.process_all_batch_results("/out", {}, "act")

    def test_two_halts_raise_the_first_and_log_the_second(self, caplog):
        service, visited = _service(
            ["a.json", "b.json"], {"a.json": _halt("alpha"), "b.json": _halt("beta")}
        )

        with caplog.at_level("WARNING"), pytest.raises(RuntimeError, match="alpha"):
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json", "b.json"]
        assert "beta" in caplog.text

    def test_a_clean_pass_returns_every_output_and_raises_nothing(self):
        service, _ = _service(
            ["a.json", "b.json"], {"a.json": "/out/a.json", "b.json": "/out/b.json"}
        )

        collected = service.process_all_batch_results("/out", {}, "act")

        assert collected.written == ["/out/a.json", "/out/b.json"]


class TestOtherFatalErrorsStillStopTheirPass:
    def test_an_ordinary_runtime_error_is_raised_at_once(self):
        service, visited = _service(
            ["a.json", "b.json"],
            {"a.json": RuntimeError("provider lost the batch"), "b.json": "/out/b.json"},
        )

        with pytest.raises(RuntimeError, match="provider lost the batch"):
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json"]

    def test_an_unresolvable_expect_block_still_stops_at_once(self):
        service, visited = _service(
            ["a.json", "b.json"],
            {"a.json": ExpectationConfigurationError("bad expect"), "b.json": "/out/b.json"},
        )

        with pytest.raises(ExpectationConfigurationError):
            service.process_all_batch_results("/out", {}, "act")

        assert visited == ["a.json"]
