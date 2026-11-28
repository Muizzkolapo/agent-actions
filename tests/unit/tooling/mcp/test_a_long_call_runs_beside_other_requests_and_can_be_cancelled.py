"""A tool call runs on a worker: a ping is answered while it runs, and a cancel stops it.

A run can take minutes. Answered in line, it held up every other request, and a client
that gave up on it had no way to stop the `agac` process behind it.
"""

import io
import json
import sys
import threading
import time

from agent_actions.tooling.mcp import tools as mcp_tools
from agent_actions.tooling.mcp.server import McpServer, current_request


def _line(**message) -> str:
    return json.dumps({"jsonrpc": "2.0", **message}) + "\n"


def _replies(written: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in written.getvalue().splitlines()]


def _open_until(lines: str, written: io.StringIO, replies: int):
    """A client that sends *lines*, then stays until it has *replies* replies."""
    yield from lines.splitlines(keepends=True)
    deadline = time.monotonic() + 5
    while len(written.getvalue().splitlines()) < replies and time.monotonic() < deadline:
        time.sleep(0.01)


def test_a_request_is_answered_while_a_long_call_still_runs():
    released = threading.Event()
    server = McpServer()
    server.handle("slow", lambda params: {"waited": released.wait(5)}, in_background=True)
    server.handle("fast", lambda params: released.set() or {})
    written = io.StringIO()

    lines = _line(id=1, method="slow") + _line(id=2, method="fast")
    server.serve(_open_until(lines, written, replies=2), written)

    assert [reply["id"] for reply in _replies(written)] == [2, 1]
    assert _replies(written)[1]["result"] == {"waited": True}


def test_a_cancelled_call_is_stopped_and_gets_no_reply():
    stopped = threading.Event()
    seen = []
    server = McpServer()
    server.handle(
        "slow",
        lambda params: {"id": current_request.get(), "stopped": stopped.wait(5)},
        in_background=True,
    )
    server.on_cancel(lambda request_id: seen.append(request_id) or stopped.set())
    written = io.StringIO()
    started = _line(id="run-1", method="slow")
    # The cancel may arrive before the worker starts the call: then it never starts.
    cancel = _line(method="notifications/cancelled", params={"requestId": "run-1"})

    server.serve(io.StringIO(started + cancel + _line(id=3, method="ping")), written)

    assert [reply["id"] for reply in _replies(written)] == [3]
    assert seen == ["run-1"]


def test_a_cancel_for_no_running_call_changes_nothing():
    server = McpServer()
    seen = []
    server.on_cancel(seen.append)
    written = io.StringIO()

    server.serve(
        io.StringIO(
            _line(method="notifications/cancelled", params={"requestId": 9})
            + _line(id=1, method="ping")
        ),
        written,
    )

    assert seen == []
    assert [reply["id"] for reply in _replies(written)] == [1]


def test_what_still_runs_when_the_client_leaves_is_stopped():
    stopped = threading.Event()
    server = McpServer()
    server.handle("slow", lambda params: {"stopped": stopped.wait(5)}, in_background=True)
    server.on_cancel(lambda request_id: stopped.set())
    written = io.StringIO()
    began = time.monotonic()

    server.serve(io.StringIO(_line(id=1, method="slow")), written)

    assert time.monotonic() - began < 4
    assert written.getvalue() == ""


def test_stopping_a_call_ends_the_command_it_runs():
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    result = {}

    def run():
        result["done"] = mcp_tools._execute(command, timeout=30, request_id="r1")

    worker = threading.Thread(target=run)
    worker.start()
    for _ in range(100):
        if "r1" in mcp_tools._running:
            break
        time.sleep(0.05)

    assert mcp_tools.stop_call("r1")
    worker.join(timeout=15)

    assert not worker.is_alive()
    assert result["done"].returncode != 0
    assert not mcp_tools.stop_call("r1")
    mcp_tools._stopped.discard("r1")
