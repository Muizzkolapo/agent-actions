"""Each fault a sandbox scenario asks for, shown as a real OpenAI-style vendor shows it.

Online, a rate limit, a timeout and a server error are raised through the shared
``wrap_vendor_error``, and a refusal, an empty answer, a cut-off answer and text that is
not JSON end as the real chat clients end them (``chat_no_answer`` and the parse errors
they store). In a batch, each is the result line such a vendor writes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent_actions.llm.providers.error_wrapper import (
    VendorErrorMapping,
    chat_no_answer,
    cut_off_parse_error,
    unparsed_json_record,
    wrap_vendor_error,
)

VENDOR = "agac-provider"
REFUSAL = "I can't help with that request."
# Raised before any answer exists.
TRANSPORT = frozenset({"rate_limit", "timeout", "server_error"})
# Cut from the honest answer.
NEEDS_ANSWER = frozenset({"truncated"})
# Holds no brace, so no JSON repair can read an object out of it.
NOT_JSON = "Here is the answer you asked for, written out in plain words."

_MAPPING = VendorErrorMapping(vendor_name=VENDOR, status_code_error_types=(httpx.HTTPStatusError,))
_STATUS = {"rate_limit": 429, "server_error": 503}
_MESSAGES = {
    "rate_limit": "Rate limit reached for requests. Please try again later.",
    "server_error": "The server had an error while processing your request.",
    "timeout": "Request timed out.",
}
_URL = "https://agac-provider.invalid/v1/chat/completions"


def _raise_transport(kind: str, model: str) -> None:
    cause: Exception
    if kind == "timeout":
        cause = httpx.ReadTimeout(_MESSAGES[kind])
    else:
        request = httpx.Request("POST", _URL)
        response = httpx.Response(
            _STATUS[kind], request=request, json={"error": {"message": _MESSAGES[kind]}}
        )
        cause = httpx.HTTPStatusError(_MESSAGES[kind], request=request, response=response)
    raise wrap_vendor_error(cause, model, _MAPPING) from cause


def _no_answer(content: str | None, finish_reason: str, refusal: str | None, model: str) -> Any:
    ended = chat_no_answer(
        content, finish_reason, refusal, vendor_label=VENDOR, model_name=model, vendor=VENDOR
    )
    assert ended is not None
    return ended


def json_answer(kind: str, honest: Any, model: str) -> list[dict[str, Any]]:
    """What a JSON-mode call returns for *kind*; a transport fault raises instead."""
    if kind in TRANSPORT:
        _raise_transport(kind, model)
    if kind == "refusal":
        return [
            {
                "raw_response": "",
                "_parse_error": _no_answer(None, "stop", REFUSAL, model).parse_error,
            }
        ]
    if kind == "empty":
        return [
            {"raw_response": "", "_parse_error": _no_answer(None, "stop", None, model).parse_error}
        ]
    if kind == "truncated":
        text = json.dumps(honest)
        return [
            {"raw_response": text[: len(text) // 2], "_parse_error": cut_off_parse_error("length")}
        ]
    return [unparsed_json_record(NOT_JSON)]


def text_answer(kind: str, model: str) -> str:
    """What a text-mode call returns for *kind*; every fault but ``invalid_json`` raises."""
    if kind in TRANSPORT:
        _raise_transport(kind, model)
    if kind == "invalid_json":
        return NOT_JSON
    content, finish_reason, refusal = {
        "refusal": (None, "stop", REFUSAL),
        "empty": (None, "stop", None),
        "truncated": ("", "length", None),
    }[kind]
    raise _no_answer(content, finish_reason, refusal, model).error


def batch_line(kind: str, line: dict[str, Any]) -> dict[str, Any]:
    """The honest result *line* as a batch writes it for *kind*."""
    if kind == "timeout":
        return {**line, "response": None, "error": {"code": "timeout", "message": _MESSAGES[kind]}}
    if kind in _STATUS:
        body = {"error": {"message": _MESSAGES[kind], "type": kind, "code": kind}}
        return {**line, "response": {"status_code": _STATUS[kind], "body": body}}
    body = json.loads(json.dumps(line["response"]["body"]))
    choice = body["choices"][0]
    content = choice["message"].get("content") or ""
    if kind == "refusal":
        choice["message"].update(content=None, refusal=REFUSAL)
    elif kind == "empty":
        choice["message"]["content"] = None
    elif kind == "truncated":
        choice["message"]["content"] = content[: len(content) // 2]
        choice["finish_reason"] = "length"
    else:
        choice["message"]["content"] = NOT_JSON
    return {**line, "response": {**line["response"], "body": body}}
