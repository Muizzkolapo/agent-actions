"""A stub OpenAI-compatible chat server that records what it was handed.

Each reply is built from the request: `honour` mode returns an object with every
property of the schema the request carried, `ignore` returns JSON that matches no
schema, and `prose` returns text that is not JSON. A queue of status codes answers
the next requests before the mode does, so a 429 followed by a 200 is one line.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CHAT_PATH = "/v1/chat/completions"


def reply_for_schema(schema: dict[str, Any] | None, model: str) -> dict[str, Any]:
    """An object that matches *schema* (the OpenAI json_schema dialect) by property type."""
    properties = ((schema or {}).get("schema") or schema or {}).get("properties") or {}
    reply: dict[str, Any] = {}
    for name, definition in properties.items():
        kind = definition.get("type") if isinstance(definition, dict) else None
        if isinstance(definition, dict) and definition.get("enum"):
            reply[name] = definition["enum"][0]
        elif kind in ("integer", "number"):
            reply[name] = 1
        elif kind == "boolean":
            reply[name] = True
        elif kind == "array":
            reply[name] = []
        elif kind == "object":
            reply[name] = {}
        else:
            reply[name] = f"{name} from {model}"
    return reply


class FakeEndpoint:
    """One server; `requests` holds every request in order."""

    def __init__(self, mode: str = "honour", statuses: list[int] | None = None) -> None:
        self.mode = mode
        self.statuses = list(statuses or [])
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def __enter__(self) -> FakeEndpoint:
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("content-length", 0)))
                try:
                    body: Any = json.loads(raw)
                except ValueError:
                    body = raw.decode(errors="replace")
                endpoint.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": body,
                    }
                )
                status, payload = endpoint._answer(body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                if status == 429:
                    self.send_header("retry-after", "0")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def _answer(self, body: Any) -> tuple[int, dict[str, Any]]:
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return status, {"error": {"message": f"stub answered {status}", "type": "stub"}}
        model = body.get("model") if isinstance(body, dict) else None
        response_format = body.get("response_format") if isinstance(body, dict) else None
        schema = (response_format or {}).get("json_schema")
        if self.mode == "honour":
            content = json.dumps(reply_for_schema(schema, str(model)))
        elif self.mode == "ignore":
            content = json.dumps({"wrong": 1})
        elif self.mode == "prose":
            content = "Sure! Here is the summary you asked for."
        else:
            raise ValueError(f"unknown mode {self.mode!r}")
        return 200, {
            "id": "stub-1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
