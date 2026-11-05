"""A stub OpenAI-compatible chat server that records what it was handed.

`honour` replies match the schema the request carried, `ignore` replies match none,
`prose` is not JSON; a status queue answers first. As a program (`--honour PORT
--ignore PORT`) it serves the sample project's probe and prints each request's headers.
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

    def __init__(
        self, mode: str = "honour", statuses: list[int] | None = None, echo_headers: bool = False
    ) -> None:
        self.mode = mode
        self.statuses = list(statuses or [])
        # A gateway's error body often quotes the request; this one does on demand.
        self.echo_headers = echo_headers
        # When set, every 200 reply carries exactly this text as the content.
        self.content: str | None = None
        # When set, every error reply carries exactly this message.
        self.error_message: str | None = None
        # A credential the server no longer takes: every request carrying it gets a 401.
        self.refuse_authorization: str | None = None
        self._refusal_barrier: threading.Barrier | None = None
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self, port: int = 0) -> FakeEndpoint:
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(self))
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __enter__(self) -> FakeEndpoint:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def refuse_credential(self, authorization: str, together: int = 1) -> None:
        """Refuse every request carrying *authorization* with a 401.

        With *together* above one, each such request is held until that many have arrived,
        so parallel callers are refused at once rather than one renewing before the rest send.
        """
        self.refuse_authorization = authorization
        self._refusal_barrier = threading.Barrier(together) if together > 1 else None

    def answer(self, body: Any, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if self.refuse_authorization and headers.get("authorization") == self.refuse_authorization:
            if self._refusal_barrier is not None:
                try:
                    self._refusal_barrier.wait(timeout=10)
                except threading.BrokenBarrierError:
                    pass
            return 401, {"error": {"message": "credential no longer accepted", "type": "stub"}}
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                message = self.error_message or f"stub answered {status}"
                if self.echo_headers:
                    message += " for request headers " + json.dumps(self.requests[-1]["headers"])
                return status, {"error": {"message": message, "type": "stub"}}
        model = body.get("model") if isinstance(body, dict) else None
        response_format = body.get("response_format") if isinstance(body, dict) else None
        schema = (response_format or {}).get("json_schema")
        if self.content is not None:
            content = self.content
        elif self.mode == "honour":
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


def _handler_for(endpoint: FakeEndpoint) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            try:
                body: Any = json.loads(raw)
            except ValueError:
                body = raw.decode(errors="replace")
            request = {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                # Every header line as sent, so a duplicate shows.
                "raw_headers": [(k.lower(), v) for k, v in self.headers.items()],
                "body": body,
            }
            endpoint.requests.append(request)
            status, payload = endpoint.answer(body, request["headers"])
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

    return Handler


def main(args: list[str]) -> None:
    """Serve one stub per mode on the given ports and print each request's headers."""
    import argparse

    parser = argparse.ArgumentParser(description="Stub OpenAI-compatible servers for a probe.")
    parser.add_argument("--honour", type=int, help="port for a server that honours the schema")
    parser.add_argument("--ignore", type=int, help="port for a server that ignores the schema")
    options = parser.parse_args(args)
    chosen = [(m, p) for m, p in (("honour", options.honour), ("ignore", options.ignore)) if p]
    if not chosen:
        parser.error("give --honour PORT and/or --ignore PORT")
    running = [(mode, FakeEndpoint(mode=mode).start(port)) for mode, port in chosen]
    for mode, endpoint in running:
        print(f"{mode}: {endpoint.base_url}", flush=True)
    printed = dict.fromkeys(range(len(running)), 0)
    stop = threading.Event()
    try:
        while not stop.wait(0.5):
            for index, (mode, endpoint) in enumerate(running):
                for request in endpoint.requests[printed[index] :]:
                    print(f"{mode} {json.dumps(request['headers'])}", flush=True)
                printed[index] = len(endpoint.requests)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
