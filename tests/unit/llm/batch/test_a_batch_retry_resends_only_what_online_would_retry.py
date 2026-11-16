"""A batch retry resends only a record whose failure online would retry.

Online, the retry policy retries a rate limit, a server or network error and a truncated answer,
and fails any other error at once (`is_retriable_error`). Batch resent every unanswered record
until `max_attempts` was spent: a 400 for a bad request, a refusal and a safety block came back
the same way each round and ended EXHAUSTED instead of FAILED with what the provider said.

A result whose line does not say why it failed is still resent, as before.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services import retry_ops
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.retry_serialization import (
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.providers.error_wrapper import VendorErrorMapping, wrap_vendor_error
from agent_actions.llm.providers.gemini.batch_client import GeminiBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.processing.recovery.retry import is_retriable_error
from agent_actions.processing.types import ProcessingStatus

ACTION = "label_page"
PARENT = "pages.json"
OK_ID = "rec-ok"
ERR_ID = "rec-errored"
AGENT_CONFIG = {
    "kind": "llm",
    "action_name": ACTION,
    "retry": {"enabled": True, "max_attempts": 3},
}


def _ok(custom_id: str) -> BatchResult:
    return BatchResult(custom_id=custom_id, content={"topic": "models"}, success=True)


def _errored(status: int | None, error: str = "HTTP error") -> BatchResult:
    return BatchResult(
        custom_id=ERR_ID, content=None, success=False, error=error, error_status=status
    )


def _no_content(finish_reason: str) -> BatchResult:
    return BatchResult(
        custom_id=ERR_ID,
        content=None,
        success=True,
        metadata={"finish_reason": finish_reason},
    )


def _bare(cls: type, **attrs: Any) -> Any:
    client = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


# ---------------------------------------------------------------------------
# The decision matches online's
# ---------------------------------------------------------------------------


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


_ONLINE = VendorErrorMapping(vendor_name="Vendor", status_code_error_types=(_StatusError,))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 502, 503, 504])
def test_a_status_is_resent_exactly_when_online_retries_it(status):
    online = is_retriable_error(wrap_vendor_error(_StatusError(status), "m", _ONLINE))

    assert BatchResultReconciler.is_retriable(_errored(status)) is online


def test_a_transient_400_online_retries_is_resent():
    result = _errored(400, "HTTP 400: Could not parse the JSON body of your request")

    assert BatchResultReconciler.is_retriable(result) is True


def test_a_failure_whose_line_gives_no_status_is_resent():
    assert BatchResultReconciler.is_retriable(_errored(None, "rate_limit_exceeded")) is True


@pytest.mark.parametrize("reason", ["stop", "content_filter", None])
def test_an_answer_with_no_content_is_not_resent(reason):
    """A refusal or a safety block: online returns it as an empty answer and never retries it."""
    assert BatchResultReconciler.is_retriable(_no_content(reason)) is False


@pytest.mark.parametrize("reason", ["length", "max_tokens"])
def test_an_answer_cut_off_before_any_content_is_resent(reason):
    """Online raises ResponseTruncatedError here, which its retry policy retries."""
    assert BatchResultReconciler.is_retriable(_no_content(reason)) is True


def test_retriable_ids_leaves_out_a_permanent_failure():
    ids = BatchResultReconciler.retriable_ids({ERR_ID, "rec-missing"}, [_ok(OK_ID), _errored(400)])

    assert ids == {"rec-missing"}


# ---------------------------------------------------------------------------
# Each client says what status a failed line carries
# ---------------------------------------------------------------------------


def test_an_openai_line_carries_its_status_and_the_vendor_message():
    line = {
        "custom_id": ERR_ID,
        "response": {
            "status_code": 400,
            "body": {"error": {"message": "Invalid schema for response_format", "type": "x"}},
        },
        "error": None,
    }

    result = _bare(OpenAIBatchClient).parse_provider_response(line)

    assert (result.success, result.error_status) == (False, 400)
    assert result.error == "HTTP 400: Invalid schema for response_format"


def test_an_openai_line_failed_before_any_request_has_no_status():
    line = {"custom_id": ERR_ID, "response": None, "error": {"code": "batch_expired"}}

    assert _bare(OpenAIBatchClient).parse_provider_response(line).error_status is None


@pytest.mark.parametrize(
    ("error_type", "status"),
    [("invalid_request_error", 400), ("rate_limit_error", 429), ("overloaded_error", 529)],
)
def test_an_anthropic_errored_result_carries_the_status_of_its_error_type(error_type, status):
    line = {
        "custom_id": ERR_ID,
        "result": {
            "type": "errored",
            "error": {"type": "error", "error": {"type": error_type, "message": "m"}},
        },
    }

    result = _bare(AnthropicBatchClient).parse_provider_response(line)

    assert result.error_status == status


def test_an_expired_anthropic_result_has_no_status():
    line = {"custom_id": ERR_ID, "result": {"type": "expired"}}

    assert _bare(AnthropicBatchClient).parse_provider_response(line).error_status is None


def test_a_gemini_error_carries_its_code():
    line = {"key": ERR_ID, "error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}}

    assert _bare(GeminiBatchClient).parse_provider_response(line).error_status == 400


def test_a_gemini_answer_with_no_candidate_is_an_answer_with_no_content():
    """A prompt the safety filter blocked: the request was answered, with nothing in it."""
    line = {"key": ERR_ID, "response": {"promptFeedback": {"blockReason": "SAFETY"}}}

    result = _bare(GeminiBatchClient).parse_provider_response(line)

    assert BatchResultReconciler.is_retriable(result) is False


def test_the_status_survives_a_deferred_round():
    (restored,) = deserialize_results(serialize_results([_errored(400)]))

    assert restored.error_status == 400


# ---------------------------------------------------------------------------
# Live path: parent batch, retry rounds, finalization
# ---------------------------------------------------------------------------


class _MetadataBackend:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def delete_metadata(self, key: str) -> bool:
        return self.store.pop(key, None) is not None


class _Harness:
    """The parent batch answers OK_ID and fails ERR_ID with *parent*; retries return *retry*."""

    def __init__(self, parent: BatchResult, retry: list[BatchResult] | None = None) -> None:
        self.backend = _MetadataBackend()
        entry = BatchJobEntry(
            batch_id="batch_parent",
            status=BatchStatus.COMPLETED,
            timestamp="2026-09-01T09:00:00+00:00",
            provider="ollama_local",
            record_count=2,
            file_name=PARENT,
        )
        self.backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
            {PARENT: entry.to_dict()}
        )
        self.manager = BatchRegistryManager(self.backend, ACTION)
        self.parent = parent
        self.retry = retry or []
        self.submitted_ids: list[set[str]] = []
        self.finalized: list[dict] = []

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=lambda _: self.manager,
            storage_backend=self.backend,
            workflow_name=ACTION,
        )
        service._client_resolver.get_for_batch_id.side_effect = self._resolve
        service._context_manager.load_batch_context_map.return_value = {
            OK_ID: {"user_content": "one", "source_guid": OK_ID},
            ERR_ID: {"user_content": "two", "source_guid": ERR_ID},
        }
        retry_service = MagicMock()
        retry_service.submit_retry_batch.side_effect = self._submit
        retry_service.process_retry_results.side_effect = retry_ops.process_retry_results
        retry_service.build_exhausted_recovery.side_effect = retry_ops.build_exhausted_recovery
        service._retry_service = retry_service
        self.service = service

    def _resolve(self, batch_id, registry_manager, *_a, **_kw):
        entry = registry_manager.get_batch_job_by_id(batch_id)
        if entry is None:
            raise ConfigurationError(f"Cannot determine client for batch_id {batch_id}")
        provider = MagicMock()
        provider.check_status.return_value = entry.status
        provider.retrieve_results.return_value = (
            [_ok(OK_ID), self.parent] if batch_id == "batch_parent" else list(self.retry)
        )
        return provider

    def _submit(self, *, missing_ids, **_kw):
        self.submitted_ids.append(set(missing_ids))
        return (f"batch_retry_{len(self.submitted_ids)}", len(missing_ids))

    def run_pass(self):
        def capture(batch_results, **kw):
            self.finalized.append(
                {"batch_results": batch_results, "exhausted": kw.get("exhausted_recovery")}
            )
            return ([], MagicMock(), None)

        with (
            patch.object(
                self.service, "_convert_batch_results_to_workflow_format", side_effect=capture
            ),
            patch.object(self.service, "_write_batch_output"),
        ):
            return self.service.process_all_batch_results("/out", AGENT_CONFIG, action_name=ACTION)

    def complete(self, batch_id: str) -> None:
        assert self.manager.update_status(batch_id, BatchStatus.COMPLETED)


def test_a_bad_request_is_not_resent():
    h = _Harness(_errored(400, "HTTP 400: Invalid schema"))
    h.run_pass()

    assert h.submitted_ids == []
    assert h.finalized[-1]["exhausted"] is None


def test_a_rate_limited_record_is_still_resent():
    h = _Harness(_errored(429, "HTTP 429"))
    h.run_pass()

    assert h.submitted_ids == [{ERR_ID}]


def test_a_retry_answered_with_a_bad_request_is_not_resent_again():
    h = _Harness(_errored(500, "HTTP 500"), retry=[_errored(400, "HTTP 400: Invalid schema")])
    h.run_pass()
    h.complete("batch_retry_1")
    h.run_pass()

    assert h.submitted_ids == [{ERR_ID}]
    assert not (h.finalized[-1]["exhausted"] or {}).get(ERR_ID)


def test_the_record_is_failed_with_the_vendor_message_not_exhausted():
    message = "HTTP 400: Invalid schema"
    h = _Harness(_errored(400, message))
    h.run_pass()
    finalized = h.finalized[-1]

    results = BatchResultStrategy().process(
        finalized["batch_results"],
        context_map={
            OK_ID: {"user_content": "one", "source_guid": OK_ID},
            ERR_ID: {"user_content": "two", "source_guid": ERR_ID},
        },
        agent_config=AGENT_CONFIG,
        exhausted_recovery=finalized["exhausted"],
    )

    (failed,) = [r for r in results if r.source_guid == ERR_ID]
    assert failed.status is ProcessingStatus.FAILED
    assert failed.error == message
    assert failed.recovery_metadata is None
