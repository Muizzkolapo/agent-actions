"""A sandbox run does not wait on a provider: the mock answers at once.

A retry of a transport fault runs with no backoff and no Retry-After wait, and the log
names the wait that was skipped. A batch result fetch that fails is tried again at once.
Outside a sandbox run each wait is as before. The scenario's ``latency_ms`` is the only
wait a sandbox call has.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.config import sandbox
from agent_actions.errors import NetworkError, RateLimitError
from agent_actions.llm.providers import batch_base
from agent_actions.processing.recovery import retry as retry_module
from agent_actions.processing.recovery.retry import RetryService


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(retry_module.time, "sleep", recorded.append)
    monkeypatch.setattr(batch_base.time, "sleep", recorded.append)
    return recorded


def _fails(times: int, error: Exception):
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        if len(calls) <= times:
            raise error
        return "ok"

    return operation


def _info(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == retry_module.__name__]


def test_a_sandbox_retry_does_not_sleep_and_logs_the_backoff_it_skipped(sleeps, caplog):
    service = RetryService(max_attempts=3, base_delay=4.0, max_delay=60.0)

    with sandbox.sandbox_mode(True), caplog.at_level(logging.INFO, logger=retry_module.__name__):
        result = service.execute(_fails(2, NetworkError("Request timed out.")), context="extract")

    assert (result.response, result.attempts) == ("ok", 3)
    assert sleeps == []
    logged = _info(caplog)
    assert len(logged) == 2
    assert logged[0].startswith(
        "Retry attempt 1/3 (extract): network_error - Request timed out. ("
    )
    assert all(line.endswith("s; skipped in sandbox)") and "(backoff " in line for line in logged)


def test_outside_a_sandbox_the_same_retry_sleeps_its_backoff(sleeps, caplog):
    service = RetryService(max_attempts=3, base_delay=4.0, max_delay=60.0)

    with caplog.at_level(logging.INFO, logger=retry_module.__name__):
        result = service.execute(_fails(2, NetworkError("Request timed out.")), context="extract")

    assert (result.response, result.attempts) == ("ok", 3)
    assert len(sleeps) == 2
    assert 0 <= sleeps[0] <= 4.0 and 0 <= sleeps[1] <= 8.0
    assert not any("skipped in sandbox" in line for line in _info(caplog))


@pytest.mark.parametrize(
    ("retry_after", "named"),
    [
        (3.0, "(waiting 3.00s, as the provider's Retry-After asked; skipped in sandbox)"),
        (120.0, "(provider asked for 120.00s; waiting max_delay 5.00s; skipped in sandbox)"),
    ],
)
def test_a_sandbox_retry_does_not_wait_a_retry_after_either(sleeps, caplog, retry_after, named):
    error = RateLimitError("too many requests", context={"retry_after": retry_after})
    service = RetryService(max_attempts=2, base_delay=1.0, max_delay=5.0)

    with sandbox.sandbox_mode(True), caplog.at_level(logging.INFO, logger=retry_module.__name__):
        result = service.execute(_fails(1, error))

    assert result.response == "ok"
    assert sleeps == []
    assert [line[line.index("(") :] for line in _info(caplog)] == [named]


@pytest.mark.parametrize(("active", "waited"), [(True, []), (False, [2.0, 4.0])])
def test_a_failed_batch_fetch_is_tried_again_at_once_only_in_a_sandbox(sleeps, active, waited):
    fetch = batch_base.retry(max_attempts=3, delay=2.0)(_fails(2, OSError("reset")))

    with sandbox.sandbox_mode(active):
        fetched = fetch()

    assert fetched == "ok"
    assert sleeps == waited
