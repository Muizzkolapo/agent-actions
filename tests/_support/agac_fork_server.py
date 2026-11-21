"""A warm process that answers each `agac` call with a fork of itself.

Run by file path, never with `-m`: Click names the program after `__main__.__package__`,
so a `-m` start makes every usage line read `python -m ...` instead of `agac`.

Each request gets a supervisor fork that forks the agac child, waits, and sends back the
exit status and output; the warm process never waits, so calls run concurrently. The
child sets again what a fresh interpreter reads at startup: the environment (in place:
`Endpoint.resolved_url` holds `os.environ` as a default), cwd, argv, time zone, the temp
dir an import cached, and stdout/stderr. If the caller hangs up (a timeout, Ctrl-C, a dead
pytest), the supervisor kills the child, as `subprocess.run` does.

A variable the package sets as it is imported is set again in each child, unless the
call sets it: a fresh agac that uses `os.environ.setdefault` does the same.

Known differences from a fresh process: every call shares the warm process's string hash
seed; stdout and stderr are unlinked files, not pipes; a traceback starts in this file; a
variable the import sets without regard to the environment still yields to the call's.
"""

from __future__ import annotations

import gc
import importlib
import json
import os
import select
import shutil
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
from typing import Any

_LENGTH = struct.Struct("!Q")
READY = b"ready\n"


def send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(_LENGTH.pack(len(data)) + data)


def recv_frame(sock: socket.socket) -> bytes:
    (length,) = _LENGTH.unpack(_recv_exact(sock, _LENGTH.size))
    return _recv_exact(sock, length)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    while size:
        chunk = sock.recv(min(size, 1 << 20))
        if not chunk:
            raise ConnectionError("the other end closed the connection")
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)


def _reap() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _serve(listener: socket.socket, parent: int, directory: str) -> dict[str, Any]:
    """Fork a supervisor for each connection. Returns only in an agac child."""
    while True:
        _reap()
        if os.getppid() != parent:
            shutil.rmtree(directory, ignore_errors=True)
            raise SystemExit(0)
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            continue
        sys.stdout.flush()
        sys.stderr.flush()
        if os.fork() == 0:
            listener.close()
            return _supervise(conn)
        conn.close()


def _supervise(conn: socket.socket) -> dict[str, Any]:
    """Run one request in a child and report it. Returns only in that child."""
    try:
        conn.settimeout(None)
        request = json.loads(recv_frame(conn))
        out = tempfile.TemporaryFile()
        err = tempfile.TemporaryFile()
        # Installed before the fork, so an exit that comes at once still wakes the wait.
        wake_read, wake_write = os.pipe()
        os.set_blocking(wake_write, False)
        signal.set_wakeup_fd(wake_write)
        signal.signal(signal.SIGCHLD, lambda signum, frame: None)
        pid = os.fork()
    except BaseException:
        traceback.print_exc()
        os._exit(70)
    if pid == 0:
        signal.set_wakeup_fd(-1)
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        os.close(wake_read)
        os.close(wake_write)
        conn.close()
        _connect_standard_streams(out.fileno(), err.fileno())
        out.close()
        err.close()
        return request
    try:
        send_frame(conn, json.dumps({"pid": pid}).encode())
        status = _wait_unless_hung_up(pid, conn, wake_read)
        if status is None:
            os._exit(0)
        send_frame(conn, json.dumps({"returncode": os.waitstatus_to_exitcode(status)}).encode())
        for stream in (out, err):
            stream.seek(0)
            send_frame(conn, stream.read())
    except BaseException:
        traceback.print_exc()
        os._exit(71)
    os._exit(0)


def _wait_unless_hung_up(pid: int, conn: socket.socket, wake_read: int) -> int | None:
    """The child's wait status, or None after killing it because the caller hung up."""
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return status
        readable, _, _ = select.select([conn, wake_read], [], [])
        if wake_read in readable:
            os.read(wake_read, 512)
        if conn in readable and not conn.recv(1, socket.MSG_PEEK):
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            return None


def _connect_standard_streams(stdout_fd: int, stderr_fd: int) -> None:
    # File descriptor 0 is already /dev/null: the client starts this process with it.
    os.dup2(stdout_fd, 1)
    os.dup2(stderr_fd, 2)


def _become_agac(request: dict[str, Any], set_at_import: dict[str, str]) -> None:
    os.chdir(request["cwd"])
    os.environ.clear()
    os.environ.update(request["env"])
    # A fresh agac sets these as it imports the package, after it read its environment.
    for key, value in set_at_import.items():
        os.environ.setdefault(key, value)
    time.tzset()
    tempfile.tempdir = None
    sys.argv = list(request["argv"])


def main() -> None:
    socket_path, agac = sys.argv[1], sys.argv[2]
    # A script's sys.path[0] is the folder of its resolved path.
    sys.path[0] = os.path.dirname(os.path.realpath(agac))
    before_import = dict(os.environ)
    importlib.import_module("agent_actions.cli.main")
    set_at_import = {
        key: value for key, value in os.environ.items() if before_import.get(key) != value
    }
    # The child's normal interpreter exit would otherwise walk every imported object
    # (about 0.17 s against 0.05 s on the audit machine); frozen objects are skipped.
    gc.freeze()
    if threading.active_count() != 1:
        raise SystemExit(
            f"the warm agac process must hold one thread before it forks; "
            f"it holds {threading.active_count()}: {[t.name for t in threading.enumerate()]}"
        )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(64)
    listener.settimeout(1.0)
    parent = os.getppid()
    sys.stdout.buffer.write(READY)
    sys.stdout.flush()

    request = _serve(listener, parent, os.path.dirname(socket_path))

    _become_agac(request, set_at_import)
    module_name, function_name = request.get("entry", "agent_actions.cli.main:main").split(":")
    sys.exit(getattr(importlib.import_module(module_name), function_name)())


if __name__ == "__main__":
    main()
