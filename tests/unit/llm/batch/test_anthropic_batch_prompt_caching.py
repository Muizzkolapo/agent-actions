"""An action's `enable_prompt_caching` reaches each Anthropic batch request, as it reaches online."""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver

PROMPT = "Summarise the page."
CONTENT = {"page": "alpha"}
USER_TEXT = json.dumps(CONTENT)
MARK = {"type": "ephemeral"}
ROW = {"target_id": "r1", "content": CONTENT, "prompt": PROMPT}
PARAM_KEYS = set(typing.get_type_hints(MessageCreateParamsNonStreaming))


def _action(**settings: Any) -> dict[str, Any]:
    return {
        "agent_type": "summarize",
        "model_vendor": "anthropic",
        "model_name": "claude-sonnet-4-6",
        "api_key": "TEST_ANTHROPIC_KEY",
        **settings,
    }


class _Entry:
    provider = "anthropic"


class _Registry:
    def get_batch_job_by_id(self, batch_id: str) -> _Entry:
        return _Entry()


def _first_submission(resolver: BatchClientResolver, action: dict[str, Any]) -> Any:
    return resolver.get_for_config(action)


def _retry_or_repair(resolver: BatchClientResolver, action: dict[str, Any]) -> Any:
    return resolver.get_for_batch_id("msgbatch_1", _Registry(), None, agent_config=action)


ROUTES = pytest.mark.parametrize(
    "route", [_first_submission, _retry_or_repair], ids=["first_submission", "retry_or_repair"]
)


def _params(client: Any) -> dict[str, Any]:
    (task,) = client.prepare_tasks([dict(ROW)], {"model_name": "claude-sonnet-4-6"})
    return task["params"]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-ant-test")


@ROUTES
class TestEachRouteMarksTheRequestForCaching:
    def test_caching_on_marks_the_system_prompt_and_the_message(self, route):
        params = _params(route(BatchClientResolver(), _action(enable_prompt_caching=True)))

        assert params["system"] == [{"type": "text", "text": PROMPT, "cache_control": MARK}]
        assert params["messages"] == [
            {
                "role": "user",
                "content": [{"type": "text", "text": USER_TEXT, "cache_control": MARK}],
            }
        ]

    def test_caching_on_sends_only_fields_a_batch_request_takes(self, route):
        params = _params(route(BatchClientResolver(), _action(enable_prompt_caching=True)))

        assert "extra_headers" not in params
        assert set(params) - PARAM_KEYS == set()

    def test_caching_off_sends_plain_text(self, route):
        params = _params(route(BatchClientResolver(), _action(enable_prompt_caching=False)))

        assert params["system"] == PROMPT
        assert params["messages"] == [{"role": "user", "content": USER_TEXT}]
        assert "extra_headers" not in params


class TestACachingClientWritesAValidRequestLine:
    def test_no_header_is_written_into_the_params(self):
        from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient

        params = _params(AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=True))

        assert "extra_headers" not in params
        assert set(params) - PARAM_KEYS == set()


class TestActionsThatDifferOnlyInCachingDoNotShareAClient:
    def test_the_first_submission_builds_one_client_for_each(self):
        resolver = BatchClientResolver()

        on = resolver.get_for_config(_action(enable_prompt_caching=True))
        off = resolver.get_for_config(_action(enable_prompt_caching=False))

        assert (on.enable_prompt_caching, off.enable_prompt_caching) == (True, False)

    def test_a_retry_does_not_take_the_other_actions_client(self):
        resolver = BatchClientResolver()
        resolver.get_for_config(_action(enable_prompt_caching=True))

        retry = _retry_or_repair(resolver, _action(enable_prompt_caching=False))

        assert retry.enable_prompt_caching is False


class TestTheSubmittedBatch:
    def _submit(self, tmp_path: Path, caching: bool) -> httpx.Request:
        import anthropic

        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "msgbatch_1",
                    "type": "message_batch",
                    "processing_status": "in_progress",
                    "request_counts": {
                        "processing": 1,
                        "succeeded": 0,
                        "errored": 0,
                        "canceled": 0,
                        "expired": 0,
                    },
                    "created_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2026-01-02T00:00:00Z",
                    "ended_at": None,
                    "archived_at": None,
                    "cancel_initiated_at": None,
                    "results_url": None,
                },
            )

        client = BatchClientResolver().get_for_config(_action(enable_prompt_caching=caching))
        client.client = anthropic.Anthropic(
            api_key="sk-ant-test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        (task,) = client.prepare_tasks([dict(ROW)], {"model_name": "claude-sonnet-4-6"})
        client.submit_batch([task], "pages", str(tmp_path))
        (request,) = sent
        return request

    def test_caching_on_sends_the_marks_and_the_caching_header(self, tmp_path):
        request = self._submit(tmp_path, caching=True)
        (line,) = json.loads(request.content)["requests"]

        assert request.headers.get("anthropic-beta") == "prompt-caching-2024-07-31"
        assert line["params"]["system"][0]["cache_control"] == MARK
        assert "extra_headers" not in line["params"]

    def test_caching_off_sends_neither(self, tmp_path):
        request = self._submit(tmp_path, caching=False)
        (line,) = json.loads(request.content)["requests"]

        assert request.headers.get("anthropic-beta") is None
        assert line["params"]["system"] == PROMPT
