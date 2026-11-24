"""An SDK imported before agent_actions keeps building its models on first use.

agent_actions sets DEFER_PYDANTIC_BUILD=false, but each SDK reads it once, at its own
import, so a program that imports openai, anthropic or groq first keeps the lazy build.
Pydantic's rebuild is not thread-safe, and a window of `record_concurrency` records
parses its first responses on several threads together. The client module therefore
builds the models a response reaches when it is imported: a parse must build none.

Each case runs in a new interpreter, because import order is fixed once per process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests._support.agac_cli import REPO

_PARSE = """
import importlib, inspect, json, sys

sdk = sys.argv[1]
importlib.import_module(sdk)
models = importlib.import_module(sdk + "._models")
importlib.import_module("agent_actions.llm.providers." + sdk + ".client")


def unbuilt():
    found, stack = set(), [models.BaseModel]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                stack.append(sub)
    return {cls for cls in found if not cls.__pydantic_complete__}


payload, events = json.loads(sys.argv[2]), json.loads(sys.argv[3])
before = unbuilt()
if sdk == "anthropic":
    from anthropic.lib.streaming._messages import accumulate_event, build_events
    from anthropic.types import Message, RawMessageStreamEvent

    models.construct_type(type_=Message, value=payload)
    takes_bufs = "json_bufs" in inspect.signature(accumulate_event).parameters
    bufs = {"json_bufs": {}} if takes_bufs else {}
    snapshot = None
    for raw in events:
        event = models.construct_type(type_=RawMessageStreamEvent, value=raw)
        snapshot = accumulate_event(event=event, current_snapshot=snapshot, **bufs)
        build_events(event=event, message_snapshot=snapshot)
    snapshot.to_dict()
else:
    response = importlib.import_module(sdk + ".types.chat").ChatCompletion
    models.construct_type(type_=response, value=payload).to_dict()
print(json.dumps(sorted(cls.__qualname__ for cls in before - unbuilt())))
"""

_CHAT_COMPLETION = {
    "id": "c",
    "object": "chat.completion",
    "created": 1,
    "model": "m",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "{}",
                "tool_calls": [
                    {"id": "t", "type": "function", "function": {"name": "f", "arguments": "{}"}}
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}

_MESSAGE = {
    "id": "m",
    "type": "message",
    "role": "assistant",
    "model": "m",
    "content": [
        {"type": "text", "text": "{}"},
        {"type": "tool_use", "id": "t", "name": "f", "input": {}},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}

_MESSAGE_STREAM = [
    {"type": "message_start", "message": {**_MESSAGE, "content": []}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "{}"}},
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "t", "name": "f", "input": {}},
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": "{}"},
    },
    {"type": "content_block_stop", "index": 1},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 1},
    },
    {"type": "message_stop"},
]


@pytest.mark.parametrize(
    ("sdk", "payload", "events"),
    [
        pytest.param("openai", _CHAT_COMPLETION, [], id="openai"),
        pytest.param("anthropic", _MESSAGE, _MESSAGE_STREAM, id="anthropic"),
        pytest.param("groq", _CHAT_COMPLETION, [], id="groq"),
    ],
)
def test_parsing_a_response_builds_no_model(sdk, payload, events):
    pytest.importorskip(sdk)
    env = {key: value for key, value in os.environ.items() if key != "DEFER_PYDANTIC_BUILD"}
    env["PYTHONPATH"] = str(REPO)

    done = subprocess.run(
        [sys.executable, "-c", _PARSE, sdk, json.dumps(payload), json.dumps(events)],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
