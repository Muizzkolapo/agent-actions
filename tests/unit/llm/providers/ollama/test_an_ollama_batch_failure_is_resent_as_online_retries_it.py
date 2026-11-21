"""A failed Ollama batch record is resent only when online would retry the same failure.

The batch client wrote every exception as an error line with no status, and a line with
no status is resent: a 404 for a model that is not pulled was retried until `max_attempts`
was spent, where online fails it at its first attempt.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from ollama import ResponseError

from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient
from agent_actions.llm.providers.ollama.client import OllamaLocalClient
from agent_actions.processing.recovery.retry import is_retriable_error

CONFIG = {"model_name": "m", "agent_type": "act", "json_mode": False}

FAILURES: dict[str, Exception] = {
    "model not found": ResponseError("model 'm' not found, try pulling it first", 404),
    "bad request": ResponseError("invalid format", 400),
    "rate limited": ResponseError("too many requests", 429),
    "server error": ResponseError("internal error", 500),
    "unavailable": ResponseError("loading model", 503),
    "error in a streamed answer": ResponseError("unexpected EOF"),
    "connection refused": ConnectionError("Failed to connect to Ollama"),
    "read timeout": httpx.ReadTimeout("timed out"),
    "not a request failure": ValueError("unhashable options"),
}


def _online(failure: Exception) -> Exception:
    with (
        patch.dict(client_base._client_cache, clear=True),
        patch("agent_actions.llm.providers.ollama.client.Client") as sdk,
        pytest.raises(Exception) as raised,
    ):
        sdk.return_value.chat.side_effect = failure
        OllamaLocalClient.call_non_json(None, CONFIG, "p", {"t": "x"})
    return raised.value


def _batch(failure: Exception) -> BatchResult:
    client = OllamaBatchClient(base_url="http://localhost:11434")
    client.client = MagicMock()
    client.client.chat.side_effect = failure
    (task,) = client.prepare_tasks(
        [{"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}], CONFIG
    )
    line: Any = client._process_single_task(task, 0, 1)
    return client.parse_provider_response(line)


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_a_failure_is_resent_exactly_when_online_retries_it(case):
    failure = FAILURES[case]

    result = _batch(failure)

    assert result.success is False
    assert BatchResultReconciler.is_retriable(result) is is_retriable_error(_online(failure))


def test_a_model_that_is_not_pulled_is_failed_at_once_with_its_status():
    result = _batch(FAILURES["model not found"])

    assert result.error_status == 404
    assert BatchResultReconciler.is_retriable(result) is False
    assert "not found" in (result.error or "")


@pytest.mark.parametrize("case", ["rate limited", "server error", "connection refused"])
def test_a_transient_failure_is_still_resent(case):
    assert BatchResultReconciler.is_retriable(_batch(FAILURES[case])) is True


@pytest.mark.parametrize("case", ["not a request failure", "connection refused", "bad request"])
def test_the_stored_error_text_holds_no_retry_flag(case):
    failure = FAILURES[case]
    status = 400 if case == "bad request" else None

    assert _batch(failure).error == str(
        {
            "message": str(failure),
            "type": "ollama_local_error",
            "code": "inference_error",
            "status": status,
        }
    )


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_the_retry_decision_survives_a_round_trip_through_the_results_file(case):
    client = OllamaBatchClient(base_url="http://localhost:11434")
    client.client = MagicMock()
    client.client.chat.side_effect = FAILURES[case]
    (task,) = client.prepare_tasks(
        [{"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}], CONFIG
    )
    line = json.loads(json.dumps(client._process_single_task(task, 0, 1)))

    result = client.parse_provider_response(line)

    assert BatchResultReconciler.is_retriable(result) is is_retriable_error(_online(FAILURES[case]))
