"""The Model Context Protocol over stdio: JSON-RPC 2.0, one message a line.

Only what a tool server needs: `initialize`, `ping`, `tools/list`, `tools/call`,
`resources/list` and `resources/read`. Standard library only, so the server
starts wherever `agac` does.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import IO, Any

from agent_actions.__version__ import __version__

logger = logging.getLogger(__name__)

# Newest first. A client asking for one of these gets it; any other gets the newest.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """A JSON-RPC error to answer a request with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Handler = Callable[[dict[str, Any]], dict[str, Any]]

# The id of the request a handler is answering, so a long one can be stopped by it.
current_request: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "current_request", default=None
)
# Requests that run beside others at most; the rest wait for a free worker.
WORKERS = 4


class McpServer:
    """Answers MCP requests from a table of handlers, one line in and one line out."""

    def __init__(self, instructions: str = "") -> None:
        self._instructions = instructions
        self._handlers: dict[str, Handler] = {
            "initialize": self._initialize,
            "ping": lambda params: {},
        }
        self._in_background: set[str] = set()
        self._cancel_hooks: list[Callable[[Any], object]] = []
        self._lock = threading.Lock()
        self._running: set[Any] = set()
        self._cancelled: set[Any] = set()

    def handle(self, method: str, handler: Handler, *, in_background: bool = False) -> None:
        """Answer *method* with *handler*; one *in_background* runs beside other requests."""
        self._handlers[method] = handler
        if in_background:
            self._in_background.add(method)

    def on_cancel(self, hook: Callable[[Any], object]) -> None:
        """Call *hook* with the id of each request the client cancels while it runs."""
        self._cancel_hooks.append(hook)

    def cancel(self, request_id: Any) -> None:
        """Stop a running request; it gets no reply, as the protocol asks."""
        with self._lock:
            if request_id not in self._running or request_id in self._cancelled:
                return
            self._cancelled.add(request_id)
        for hook in self._cancel_hooks:
            hook(request_id)

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        capabilities: dict[str, Any] = {}
        if "tools/list" in self._handlers:
            capabilities["tools"] = {}
        if "resources/list" in self._handlers:
            capabilities["resources"] = {}
        result: dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": capabilities,
            "serverInfo": {"name": "agent-actions", "version": __version__},
        }
        if self._instructions:
            result["instructions"] = self._instructions
        return result

    def answer(self, line: str) -> str | None:
        """The reply to one line of input, or None when it asks for none.

        A notification (no `id`) is never answered, as the protocol requires,
        whether or not its method is known.
        """
        try:
            message = json.loads(line)
        except ValueError:
            return _error(None, PARSE_ERROR, "The message is not JSON")
        if not isinstance(message, dict) or not isinstance(message.get("method"), str):
            request_id = message.get("id") if isinstance(message, dict) else None
            return _error(request_id, INVALID_REQUEST, "The message is not a JSON-RPC request")
        method = message["method"]
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if "id" not in message:
            if method == "notifications/cancelled":
                self.cancel(params.get("requestId"))
            return None
        request_id = message["id"]
        handler = self._handlers.get(method)
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
        with self._lock:
            if request_id in self._cancelled:
                # Cancelled while it waited for a worker: it never starts.
                self._cancelled.discard(request_id)
                self._running.discard(request_id)
                return None
            self._running.add(request_id)
        token = current_request.set(request_id)
        try:
            result = handler(params)
        except RpcError as error:
            return self._unless_cancelled(
                request_id, _error(request_id, error.code, error.message)
            )
        except Exception as error:
            logger.exception("The handler of %s failed", method)
            failed = _error(request_id, INTERNAL_ERROR, f"{type(error).__name__}: {error}")
            return self._unless_cancelled(request_id, failed)
        finally:
            current_request.reset(token)
        reply = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
        return self._unless_cancelled(request_id, reply)

    def _unless_cancelled(self, request_id: Any, reply: str) -> str | None:
        with self._lock:
            self._running.discard(request_id)
            if request_id in self._cancelled:
                self._cancelled.discard(request_id)
                return None
        return reply

    def serve(self, reader: IO[str], writer: IO[str]) -> None:
        """Answer each line of *reader* on *writer* until *reader* ends.

        A method registered *in_background* runs on a worker, so a long tool call does
        not hold up a ping, a list or a cancel. When *reader* ends, the client is gone:
        what still runs is stopped.
        """
        writing = threading.Lock()

        def reply_to(line: str) -> None:
            reply = self.answer(line)
            if reply is None:
                return
            with writing:
                try:
                    writer.write(reply + "\n")
                    writer.flush()
                except (BrokenPipeError, ValueError):
                    logger.debug("The client left before a reply could be written")

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="mcp") as workers:
            for line in reader:
                if not line.strip():
                    continue
                request = self._request_of(line)
                if request is not None and request[0] in self._in_background:
                    with self._lock:
                        self._running.add(request[1])
                    workers.submit(reply_to, line)
                else:
                    reply_to(line)
            with self._lock:
                still_running = list(self._running)
            for request_id in still_running:
                self.cancel(request_id)

    @staticmethod
    def _request_of(line: str) -> tuple[str, Any] | None:
        """The method and id of a request on *line*, or None for anything else."""
        try:
            message = json.loads(line)
        except ValueError:
            return None
        if not isinstance(message, dict) or "id" not in message:
            return None
        method = message.get("method")
        return (method, message["id"]) if isinstance(method, str) else None


def _error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )
