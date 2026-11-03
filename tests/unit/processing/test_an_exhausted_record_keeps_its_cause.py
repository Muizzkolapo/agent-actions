"""A record that exhausted its retries carries the last error to the run's output (1607)."""

from agent_actions.errors import NetworkError
from agent_actions.processing.recovery.retry import RetryService
from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingResult, RecoveryMetadata, RetryMetadata


def _retry(last_error: str | None) -> RetryMetadata:
    return RetryMetadata(
        attempts=3, failures=3, succeeded=False, reason="network_error", last_error=last_error
    )


def test_the_exhausted_message_leads_with_the_last_error():
    assert _retry("Connection refused").exhausted_message() == (
        "Connection refused — retry exhausted after 3 attempts"
    )


def test_without_a_last_error_the_message_is_unchanged():
    assert _retry(None).exhausted_message() == "Retry exhausted after 3 attempts"


def test_the_last_error_survives_storage():
    stored = RecoveryMetadata(retry=_retry("Connection refused")).to_dict()
    assert RecoveryMetadata.from_dict(stored).retry.last_error == "Connection refused"


def test_metadata_stored_before_it_had_a_last_error_still_reads():
    stored = RecoveryMetadata(retry=_retry(None)).to_dict()
    assert "last_error" not in stored["retry"]
    assert RecoveryMetadata.from_dict(stored).retry.last_error is None


class _Silent(NetworkError):
    """A retriable error whose message is empty, as some transport timeouts' are."""

    def __str__(self) -> str:
        return ""


def test_an_error_with_no_message_is_named_by_its_type(monkeypatch):
    monkeypatch.setattr("agent_actions.processing.recovery.retry.time.sleep", lambda _: None)

    def times_out():
        raise _Silent("")

    result = RetryService(max_attempts=2, base_delay=0).execute(times_out)

    assert result.exhausted
    assert "_Silent" in result.last_error


def test_a_file_whose_every_record_exhausted_fails_with_their_cause():
    results = [
        ProcessingResult.exhausted(
            error=_retry("Connection refused").exhausted_message(),
            source_guid=f"g{i}",
            input_record={"value": i},
        )
        for i in range(2)
    ]

    _, stats = collect_results_from_processing_results(results, "summarize")
    failure = stats.terminal_failure("summarize", [{"value": 0}, {"value": 1}], [])

    assert failure is not None
    assert str(failure).startswith("Connection refused — retry exhausted after 3 attempts")
