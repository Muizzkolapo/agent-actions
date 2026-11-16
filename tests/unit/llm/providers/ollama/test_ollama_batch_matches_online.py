"""An Ollama batch record goes out and comes back as the online call does, through the real SDK."""

from __future__ import annotations

import json
from typing import Any

import httpx
from ollama import Client

from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient

ROW = {"target_id": "r1", "content": {"t": "x"}, "prompt": "p"}
SCHEMA = {
    "title": "S",
    "type": "object",
    "properties": {"a": {"type": "string"}},
    "required": ["a"],
}


def _run(config: dict[str, Any], done_reason: str = "stop") -> tuple[dict[str, Any], dict]:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "m",
                "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": '{"a": "x"}'},
                "done": True,
                "done_reason": done_reason,
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
        )

    client = OllamaBatchClient(base_url="http://localhost:11434")
    client.client = Client(host="http://localhost:11434", transport=httpx.MockTransport(handler))
    (task,) = client.prepare_tasks([dict(ROW)], {"model_name": "m", **config})
    result = client._process_single_task(task, 0, 1)
    assert result is not None
    (request,) = sent
    return request, result


def test_an_unset_temperature_is_not_sent():
    request, _ = _run({"json_mode": False})

    assert "temperature" not in request.get("options", {})


def test_a_set_temperature_is_sent():
    request, _ = _run({"json_mode": False, "temperature": 0.2})

    assert request["options"]["temperature"] == 0.2


def test_json_mode_without_a_schema_asks_for_json():
    request, _ = _run({"json_mode": True})

    assert request["format"] == "json"


def test_json_mode_with_a_schema_sends_the_schema():
    request, _ = _run({"json_mode": True, "compiled_schema": SCHEMA})

    assert request["format"] == {k: v for k, v in SCHEMA.items() if k != "title"}


def test_a_text_call_asks_for_no_format():
    request, _ = _run({"json_mode": False})

    assert request.get("format") in (None, "")


def test_an_answer_cut_off_at_the_limit_is_labelled_length():
    _, result = _run({"json_mode": False, "max_tokens": 5}, done_reason="length")

    assert result["response"]["body"]["choices"][0]["finish_reason"] == "length"


def test_a_finished_answer_is_labelled_stop():
    _, result = _run({"json_mode": False})

    assert result["response"]["body"]["choices"][0]["finish_reason"] == "stop"
