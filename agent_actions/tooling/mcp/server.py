"""The Model Context Protocol over stdio: JSON-RPC 2.0, one message a line.

Only what a tool server needs: `initialize`, `ping`, `tools/list`, `tools/call`,
`resources/list` and `resources/read`. Standard library only, so the server
starts wherever `agac` does.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
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


class McpServer:
    """Answers MCP requests from a table of handlers, one line in and one line out."""

    def __init__(self, instructions: str = "") -> None:
        self._instructions = instructions
        self._handlers: dict[str, Handler] = {
            "initialize": self._initialize,
            "ping": lambda params: {},
        }

    def handle(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

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
        if "id" not in message:
            return None
        request_id = message["id"]
        handler = self._handlers.get(method)
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
        params = message.get("params")
        try:
            result = handler(params if isinstance(params, dict) else {})
        except RpcError as error:
            return _error(request_id, error.code, error.message)
        except Exception as error:
            logger.exception("The handler of %s failed", method)
            return _error(request_id, INTERNAL_ERROR, f"{type(error).__name__}: {error}")
        return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})

    def serve(self, reader: IO[str], writer: IO[str]) -> None:
        """Answer each line of *reader* on *writer* until *reader* ends."""
        for line in reader:
            if not line.strip():
                continue
            reply = self.answer(line)
            if reply is not None:
                writer.write(reply + "\n")
                writer.flush()


def _error(request_id: Any, code: int, message: str) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )
