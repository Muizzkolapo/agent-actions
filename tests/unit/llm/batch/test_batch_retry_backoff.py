"""Tests for exponential backoff with jitter in BatchRetryService.retrieve_results_with_retry()."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.providers.batch_base import BatchResult


def _import_retry_service():
    """Deferred import — services/__init__.py triggers a circular import chain."""
    from agent_actions.llm.batch.services.retry import BatchRetryService

    return BatchRetryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(custom_id: str, success: bool = True) -> BatchResult:
    return BatchResult(custom_id=custom_id, content="ok", success=success)


def _run_retry_loop(
    service,
    context_map: dict,
    agent_config: dict,
    resubmit_side_effect,
):
    """Run retrieve_results_with_retry with standard mocks.

    Patches retrieve_and_reconcile (returns []), find_missing_ids (returns all
    keys from context_map), collect_result_custom_ids (returns custom_ids from
    successful results).
    """
    all_ids = set(context_map.keys())

    with (
        patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile",
            return_value=[],
        ),
        patch.object(
            service,
            "_resubmit_missing_records",
            side_effect=resubmit_side_effect,
        ),
        patch(
            "agent_actions.llm.batch.processing.reconciler.BatchResultReconciler.find_missing_ids",
            return_value=all_ids,
        ),
        patch(
            "agent_actions.llm.batch.processing.reconciler.BatchResultReconciler.collect_result_custom_ids",
            side_effect=lambda r: {res.custom_id for res in r if res.success} if r else set(),
        ),
    ):
        return service.retrieve_results_with_retry(
            provider=MagicMock(),
            batch_id="b-1",
            output_directory="/tmp",
            context_map=context_map,
            agent_config=agent_config,
        )


# ---------------------------------------------------------------------------
# Test: no sleep on first retry attempt
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
@patch("agent_actions.llm.batch.services.retry.time.sleep")
def test_no_sleep_on_first_retry_attempt(mock_sleep, _mock_uniform):
    """First retry attempt (retry_attempts=1) must not call time.sleep."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}

    def _resubmit(**kw):
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={"retry": {"enabled": True, "max_attempts": 1}},
        resubmit_side_effect=_resubmit,
    )

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Test: backoff formula — attempt 2 sleeps base_delay
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.time.sleep")
@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
def test_backoff_attempt_2_sleeps_base_delay(mock_uniform, mock_sleep):
    """Second attempt: backoff = base_delay * 2^0 = 5.0, jitter = 0 → sleep(5.0)."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}
    calls = []

    def _resubmit(**kw):
        calls.append(1)
        if len(calls) == 1:
            return []
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={
            "retry": {"enabled": True, "max_attempts": 2, "base_delay": 5.0, "max_delay": 120.0}
        },
        resubmit_side_effect=_resubmit,
    )

    mock_uniform.assert_called_once_with(0, 5.0 * 0.3)
    mock_sleep.assert_called_once_with(5.0)


# ---------------------------------------------------------------------------
# Test: backoff formula — attempt 3 doubles
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.time.sleep")
@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
def test_backoff_attempt_3_doubles(mock_uniform, mock_sleep):
    """Third attempt: backoff = base_delay * 2^1 = 10.0."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}
    calls = []

    def _resubmit(**kw):
        calls.append(1)
        if len(calls) < 3:
            return []
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={
            "retry": {"enabled": True, "max_attempts": 3, "base_delay": 5.0, "max_delay": 120.0}
        },
        resubmit_side_effect=_resubmit,
    )

    assert mock_sleep.call_count == 2
    sleep_values = [c.args[0] for c in mock_sleep.call_args_list]
    assert sleep_values[0] == pytest.approx(5.0)
    assert sleep_values[1] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Test: max_delay caps backoff
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
@patch("agent_actions.llm.batch.services.retry.time.sleep")
def test_backoff_capped_at_max_delay(mock_sleep, _mock_uniform):
    """Backoff is capped at max_delay regardless of attempt number."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}
    calls = []

    def _resubmit(**kw):
        calls.append(1)
        if len(calls) < 3:
            return []
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={
            "retry": {"enabled": True, "max_attempts": 3, "base_delay": 100.0, "max_delay": 8.0}
        },
        resubmit_side_effect=_resubmit,
    )

    for c in mock_sleep.call_args_list:
        assert c.args[0] == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Test: jitter is added to backoff
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.time.sleep")
@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=1.5)
def test_jitter_added_to_backoff(mock_uniform, mock_sleep):
    """sleep receives backoff + jitter, not just backoff."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}
    calls = []

    def _resubmit(**kw):
        calls.append(1)
        if len(calls) == 1:
            return []
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={
            "retry": {"enabled": True, "max_attempts": 2, "base_delay": 5.0, "max_delay": 120.0}
        },
        resubmit_side_effect=_resubmit,
    )

    # backoff=5.0, jitter=1.5 → sleep(6.5)
    mock_sleep.assert_called_once_with(6.5)


# ---------------------------------------------------------------------------
# Test: default config values (no base_delay/max_delay in config)
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
@patch("agent_actions.llm.batch.services.retry.time.sleep")
def test_defaults_when_config_omits_delay_keys(mock_sleep, _mock_uniform):
    """With no base_delay/max_delay in config, defaults are base_delay=5.0, max_delay=120.0."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}
    calls = []

    def _resubmit(**kw):
        calls.append(1)
        if len(calls) == 1:
            return []
        return [_make_result("id-1")]

    _run_retry_loop(
        service,
        context_map,
        agent_config={"retry": {"enabled": True, "max_attempts": 2}},
        resubmit_side_effect=_resubmit,
    )

    # Default base_delay=5.0 → attempt 2 sleeps 5.0
    mock_sleep.assert_called_once_with(5.0)


# ---------------------------------------------------------------------------
# Test: no retry config at all still uses defaults
# ---------------------------------------------------------------------------


@patch("agent_actions.llm.batch.services.retry.random.uniform", return_value=0.0)
@patch("agent_actions.llm.batch.services.retry.time.sleep")
def test_no_sleep_when_retry_disabled(mock_sleep, _mock_uniform):
    """When retry is not enabled, no backoff sleep occurs."""
    service = _import_retry_service()()
    context_map = {"id-1": {"prompt": "p"}}

    with (
        patch(
            "agent_actions.llm.batch.services.retry.retrieve_and_reconcile",
            return_value=[],
        ),
    ):
        service.retrieve_results_with_retry(
            provider=MagicMock(),
            batch_id="b-1",
            output_directory="/tmp",
            context_map=context_map,
            agent_config={},  # no retry key
        )

    mock_sleep.assert_not_called()
