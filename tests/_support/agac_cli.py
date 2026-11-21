"""Run the `agac` console script against the tree these tests live in."""

from __future__ import annotations

import atexit
import errno
import io
import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

from tests._support.agac_fork_server import READY, recv_frame, send_frame

REPO = Path(__file__).resolve().parents[2]
AGAC = Path(sys.executable).parent / "agac"
TIMEOUT_SECONDS = 300
_SERVER_SCRIPT = Path(__file__).with_name("agac_fork_server.py")
_RUNNERS = {"fork": "fork server", "fresh": "fresh interpreter"}

RUNNER = os.environ.get("AGAC_TEST_RUNNER", "fork")
if RUNNER not in _RUNNERS:
    raise ValueError(f"AGAC_TEST_RUNNER must be one of {sorted(_RUNNERS)}, not {RUNNER!r}")


def runner_header() -> str:
    return f"agac runner: {_RUNNERS[RUNNER]}"


def _merged_env(base: Mapping[str, str], env: Mapping[str, str] | None) -> dict[str, str]:
    merged = {**base, **(env or {})}
    inherited = merged.get("PYTHONPATH")
    merged["PYTHONPATH"] = os.pathsep.join([str(REPO), inherited]) if inherited else str(REPO)
    return merged


def _startup_settings(env: Mapping[str, str]) -> dict[str, str]:
    """The variables an interpreter reads once, at startup."""
    return {
        key: value
        for key, value in env.items()
        if key.startswith(("PYTHON", "LC_")) or key == "LANG"
    }


# Captured at import, before any test changes os.environ, so the warm process never
# starts with one test's PYTHONPATH.
_WARM_ENV = _merged_env(os.environ, None)


def run_agac(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None, fresh_process: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run `agac` in *cwd* with this tree first on its import path.

    The console script otherwise imports `agent_actions` from wherever the
    venv's editable install points, which from a second worktree is another
    checkout; pytest.ini's `pythonpath` reaches only the pytest process.

    A call runs in a fork of a warm process that imported the CLI already, unless
    `fresh_process` is set or its interpreter startup settings differ from the warm
    process's (a stand-in on `PYTHONPATH`, `PYTHONHASHSEED`, the locale).
    """
    merged = _merged_env(os.environ, env)
    argv = [str(AGAC), *args]
    if (
        fresh_process
        or RUNNER == "fresh"
        or _startup_settings(merged) != _startup_settings(_WARM_ENV)
    ):
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, env=merged
        )
    return _WARM.call(argv, cwd, merged)


def run_in_warm_process(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None, entry: str, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run *entry* (`module:function`) in a warm child in place of the CLI, for the control tests."""
    return _WARM.call([str(AGAC), *args], cwd, _merged_env(os.environ, env), entry, timeout)


def warm_process_pid() -> int:
    return _WARM.pid()


class WarmProcessError(RuntimeError):
    pass


def _decode(data: bytes) -> str:
    """Decode output as `subprocess.run(text=True)` does: locale encoding, universal newlines."""
    encoding = io.TextIOWrapper(io.BytesIO()).encoding
    return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")


class _WarmProcess:
    """One warm process for each pytest process; started on the first call."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._owner = 0
        self._directory = ""

    def pid(self) -> int:
        self._socket_path()
        assert self._process is not None
        return self._process.pid

    def call(
        self,
        argv: list[str],
        cwd: Path,
        env: dict[str, str],
        entry: str = "agent_actions.cli.main:main",
        timeout: float = TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        directory = os.path.abspath(cwd)
        if not os.path.isdir(directory):
            # subprocess.run raises before it starts anything; so does this call.
            missing = not os.path.exists(directory)
            error = FileNotFoundError if missing else NotADirectoryError
            code = errno.ENOENT if missing else errno.ENOTDIR
            raise error(code, os.strerror(code), str(cwd))
        path = self._socket_path()
        request = {
            "argv": [os.fspath(arg) for arg in argv],
            "cwd": directory,
            "env": {key: os.fspath(value) for key, value in env.items()},
            "entry": entry,
        }
        # Leaving this block for any reason closes the socket; the supervisor then kills
        # the child, as subprocess.run kills its child on the way out.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            try:
                sock.connect(path)
                send_frame(sock, json.dumps(request).encode())
                recv_frame(sock)  # the child's pid: the child has started
                returncode = json.loads(recv_frame(sock))["returncode"]
                stdout = recv_frame(sock)
                stderr = recv_frame(sock)
            except TimeoutError:
                raise subprocess.TimeoutExpired(argv, timeout) from None
            except OSError as error:
                raise self._failure(error) from error
        return subprocess.CompletedProcess(argv, returncode, _decode(stdout), _decode(stderr))

    def _socket_path(self) -> str:
        with self._lock:
            if self._process is None or self._owner != os.getpid():
                self._start()
            return os.path.join(self._directory, "socket")

    def _start(self) -> None:
        self._directory = tempfile.mkdtemp(prefix="agac-warm-")
        log = open(os.path.join(self._directory, "log"), "wb")
        self._process = subprocess.Popen(
            [
                sys.executable,
                str(_SERVER_SCRIPT),
                os.path.join(self._directory, "socket"),
                str(AGAC),
            ],
            cwd=self._directory,
            env=_WARM_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=log,
        )
        log.close()
        self._owner = os.getpid()
        assert self._process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(self._process.stdout, selectors.EVENT_READ)
            ready = selector.select(timeout=120) and self._process.stdout.readline() == READY
        self._process.stdout.close()
        if not ready:
            if self._process.poll() is None:
                self._process.kill()
                self._process.wait()
            raise self._failure(RuntimeError("it did not report ready within 120 s"))

    def _failure(self, error: BaseException) -> WarmProcessError:
        """Name the warm process and why it failed; the next call starts a new one."""
        with self._lock:
            process, directory = self._process, self._directory
            status = process.poll() if process else None
            try:
                with open(os.path.join(directory, "log"), errors="replace") as log:
                    tail = log.read()[-4000:]
            except OSError:
                tail = "(no log)"
            if process is not None and status is not None:
                self._process = None
                shutil.rmtree(directory, ignore_errors=True)
        pid = process.pid if process else "none"
        return WarmProcessError(
            f"the warm agac process (pid {pid}, exit status {status}) failed: {error}\n"
            f"its log ({directory}/log):\n{tail}"
        )

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if process is None or self._owner != os.getpid():
                return
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            shutil.rmtree(self._directory, ignore_errors=True)


_WARM = _WarmProcess()
atexit.register(_WARM.stop)
