"""Retry waits as long as the provider's Retry-After asks, capped at `max_delay`.

An error with no Retry-After keeps the jittered backoff. `base_delay` and `max_delay` are
read from a workflow's `retry:` block and reach the service the action runs with.
"""

from __future__ import annotations

import logging

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import NetworkError, RateLimitError
from agent_actions.output.response.expander import ActionExpander
from agent_actions.processing.recovery import retry as retry_module
from agent_actions.processing.recovery.retry import RetryService, create_retry_service_from_config

WORKFLOW = """\
name: w
description: d
defaults:
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: KEY
actions:
  - name: act
    intent: i
    kind: llm
    retry: {retry}
"""


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(retry_module.time, "sleep", recorded.append)
    return recorded


def _fails_once(error: Exception):
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise error
        return "ok"

    return operation


def _rate_limited(retry_after: float | None) -> RateLimitError:
    return RateLimitError("too many requests", context={"retry_after": retry_after})


def test_it_waits_as_long_as_the_provider_asks(sleeps):
    result = RetryService(max_attempts=2).execute(_fails_once(_rate_limited(7.0)))

    assert result.response == "ok"
    assert sleeps == [7.0]


def test_a_longer_ask_is_capped_at_max_delay_with_a_warning(sleeps, caplog):
    service = RetryService(max_attempts=2, base_delay=1.0, max_delay=5.0)

    with caplog.at_level(logging.WARNING, logger=retry_module.__name__):
        service.execute(_fails_once(_rate_limited(120.0)))

    assert sleeps == [5.0]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "120.00s" in warnings[0] and "max_delay 5.00s" in warnings[0]


def test_an_unreadable_ask_keeps_the_backoff(sleeps):
    RetryService(max_attempts=2, base_delay=0.5).execute(_fails_once(_rate_limited(float("nan"))))

    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= 0.5


@pytest.mark.parametrize("base_delay", [1.0, 2.0])
def test_without_a_retry_after_it_keeps_the_jittered_backoff(sleeps, base_delay):
    service = RetryService(max_attempts=2, base_delay=base_delay)

    service.execute(_fails_once(_rate_limited(None)))

    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= base_delay


def test_a_network_error_keeps_the_backoff(sleeps):
    RetryService(max_attempts=2, base_delay=0.5).execute(_fails_once(NetworkError("reset")))

    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= 0.5


def test_a_retry_after_of_zero_retries_at_once(sleeps):
    RetryService(max_attempts=2).execute(_fails_once(_rate_limited(0.0)))

    assert sleeps == [0.0]


def _service_from_workflow(retry: str) -> RetryService | None:
    """The retry service an action gets after load, expansion and the merge."""
    workflow = WorkflowConfig.model_validate(yaml.safe_load(WORKFLOW.format(retry=retry)))
    expanded = {
        "name": "w",
        "actions": [
            a.model_dump(mode="python", exclude_unset=True, by_alias=True) for a in workflow.actions
        ],
        "defaults": workflow.defaults.model_dump(mode="python", exclude_unset=True, by_alias=True),
    }
    agent = ActionExpander.expand_actions_to_agents(expanded)["w"][0]
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {}
    manager.tool_path = None
    manager.agent_configs = {}
    manager.merge_agent_configs([agent])
    return create_retry_service_from_config(manager.agent_configs["act"].model_dump()["retry"])


def test_delays_written_in_a_workflow_reach_the_service():
    service = _service_from_workflow("{max_attempts: 3, base_delay: 2, max_delay: 30}")

    assert service is not None
    assert (service.max_attempts, service.base_delay, service.max_delay) == (3, 2.0, 30.0)


def test_unset_delays_keep_their_defaults():
    service = _service_from_workflow("{max_attempts: 3}")

    assert service is not None
    assert (service.base_delay, service.max_delay) == (1.0, 60.0)


def test_a_zero_base_delay_is_refused_at_load():
    with pytest.raises(ValidationError) as excinfo:
        _service_from_workflow("{base_delay: 0}")

    assert "base_delay" in str(excinfo.value)
    assert "greater than 0" in str(excinfo.value)


def test_a_max_delay_below_base_delay_is_refused_at_load():
    with pytest.raises(ValidationError) as excinfo:
        _service_from_workflow("{base_delay: 10, max_delay: 5}")

    assert "max_delay (5) must be at least base_delay (10)" in str(excinfo.value)
