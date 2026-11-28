"""A client session with an MCP server over stdio: JSON-RPC 2.0, one message a line.

Standard library only, and synchronous: the server runs as a child process, a reader
thread files each reply under the id it answers, and a call waits for its own reply.
One session serves a whole run; calls from several threads share it.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess  # nosec B404
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT_SECONDS = 300.0
START_TIMEOUT_SECONDS = 60.0


class McpError(Exception):
    """The server could not be reached, refused a request, or a tool reported an error."""


class McpSession:
    """One running MCP server and the requests sent to it."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        self.name = name
        self._argv = [command, *args]
        self._env = {**os.environ, **(env or {})}
        self._cwd = cwd
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._writing = threading.Lock()
        self._replies: dict[int, dict[str, Any]] = {}
        self._arrived = threading.Condition()
        self._ended = False
        self.tools: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        """Start the server, agree on the protocol, and learn its tools."""
        try:
            self._process = subprocess.Popen(  # nosec B603
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env,
                cwd=self._cwd,
            )
        except OSError as error:
            raise McpError(
                f"MCP server '{self.name}' did not start ({' '.join(self._argv)}): {error}"
            ) from error
        threading.Thread(target=self._read, name=f"mcp-{self.name}", daemon=True).start()
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-actions", "version": _version()},
            },
            timeout=START_TIMEOUT_SECONDS,
        )
        self._notify("notifications/initialized")
        listed = self._request("tools/list", {}, timeout=START_TIMEOUT_SECONDS)
        self.tools = {
            tool["name"]: tool
            for tool in listed.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }

    def call_tool(
        self, tool: str, arguments: Mapping[str, Any], timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        """The result of *tool* called with *arguments*; a tool error raises ``McpError``."""
        if self.tools and tool not in self.tools:
            raise McpError(
                f"MCP server '{self.name}' has no tool '{tool}'. "
                f"Its tools: {', '.join(sorted(self.tools)) or 'none'}"
            )
        result = self._request(
            "tools/call", {"name": tool, "arguments": dict(arguments)}, timeout=timeout
        )
        if result.get("isError"):
            raise McpError(f"Tool '{tool}' of MCP server '{self.name}' failed: {_text_of(result)}")
        return result

    def close(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def _request(self, method: str, params: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        with self._arrived:
            self._arrived.wait_for(
                lambda: request_id in self._replies or self._ended, timeout=timeout
            )
            reply = self._replies.pop(request_id, None)
        if reply is None:
            why = "it stopped" if self._ended else f"no reply after {timeout:g}s"
            raise McpError(f"MCP server '{self.name}' did not answer {method}: {why}")
        error = reply.get("error")
        if error is not None:
            message = error.get("message") if isinstance(error, dict) else error
            raise McpError(f"MCP server '{self.name}' refused {method}: {message}")
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpError(f"MCP server '{self.name}' is not running")
        with self._writing:
            try:
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
            except OSError as error:
                raise McpError(f"MCP server '{self.name}' stopped: {error}") from error

    def _read(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                logger.debug("MCP server '%s' wrote a line that is not JSON", self.name)
                continue
            if isinstance(message, dict) and isinstance(message.get("id"), int):
                if "result" in message or "error" in message:
                    with self._arrived:
                        self._replies[message["id"]] = message
                        self._arrived.notify_all()
                    continue
            # A server request or notification: this client offers no capability to answer.
            logger.debug("MCP server '%s' sent %s; ignored", self.name, message.get("method"))
        with self._arrived:
            self._ended = True
            self._arrived.notify_all()


def result_records(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The records a tool result holds, as a tool action returns them.

    Structured content is taken as is; otherwise each text item that holds JSON is
    parsed, and one that does not is kept under ``result``.
    """
    structured = result.get("structuredContent")
    if structured is not None:
        return _as_records(structured)
    records: list[dict[str, Any]] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text", "")
        try:
            parsed = json.loads(text)
        except ValueError:
            records.append({"result": text})
            continue
        records.extend(_as_records(parsed))
    return records


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"result": item} for item in value]
    if isinstance(value, dict):
        return [value]
    return [{"result": value}]


def _text_of(result: Mapping[str, Any]) -> str:
    texts = [
        str(item.get("text", ""))
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return " ".join(texts).strip() or "no message"


def _version() -> str:
    from agent_actions.__version__ import __version__

    return str(__version__)


class SessionPool:
    """One started session per server name, for the life of the process.

    A server that did not start is not started again: each later record fails at once
    with the same error, rather than waiting for a server that will not answer.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, McpSession] = {}
        self._failed: dict[str, McpError] = {}
        self._lock = threading.Lock()
        atexit.register(self.close_all)

    def get(self, name: str, settings: Mapping[str, Any], cwd: Path | None) -> McpSession:
        with self._lock:
            if name in self._failed:
                raise self._failed[name]
            session = self._sessions.get(name)
            if session is None:
                session = McpSession(
                    name,
                    str(settings["command"]),
                    [str(arg) for arg in settings.get("args") or []],
                    {str(k): str(v) for k, v in (settings.get("env") or {}).items()},
                    cwd,
                )
                try:
                    session.start()
                except McpError as error:
                    session.close()
                    self._failed[name] = error
                    raise
                self._sessions[name] = session
            return session

    def close_all(self) -> None:
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
            self._failed = {}
        for session in sessions:
            session.close()


POOL = SessionPool()
