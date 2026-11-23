"""Throwaway database servers for the tests that hold every connection type to one contract.

A server is started from the binaries the machine has, in a directory of its
own, listening on a unix socket only. A machine without the binaries, or
without the driver, yields ``None`` and the tests for that type are skipped.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_START_SECONDS = 60


def has_driver(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _as(user: str, command: list[str]) -> list[str]:
    """*command*, run as *user* when the tests run as root: neither server starts as root."""
    return ["runuser", "-u", user, "--", *command] if os.geteuid() == 0 else command


def _server_directory(user: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="agac-db-"))
    if os.geteuid() == 0:
        shutil.chown(directory, user=user)
    directory.chmod(0o755)
    return directory


def _postgres_bin() -> Path | None:
    found = shutil.which("initdb")
    if found:
        return Path(found).parent
    versions = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"))
    return Path(versions[-1]).parent if versions else None


@contextmanager
def postgres_server() -> Iterator[dict[str, Any] | None]:
    """Settings of a ``postgres`` connection to a server started for the caller."""
    binaries = _postgres_bin()
    if binaries is None or not has_driver("psycopg"):
        yield None
        return
    directory = _server_directory("postgres")
    data = directory / "data"
    port = 54000 + os.getpid() % 1000
    options = f"-c listen_addresses='' -c unix_socket_directories={directory} -p {port}"
    try:
        subprocess.run(
            _as(
                "postgres", [str(binaries / "initdb"), "-D", str(data), "-U", "agac", "-A", "trust"]
            ),
            check=True,
            capture_output=True,
        )
        # No pipes: the server inherits them, and a pipe it holds open never reads as closed.
        subprocess.run(
            _as(
                "postgres",
                [
                    str(binaries / "pg_ctl"),
                    *("-D", str(data), "-o", options, "-l", str(directory / "server.log")),
                    *("-w", "start"),
                ],
            ),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_START_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(directory, ignore_errors=True)
        yield None
        return
    try:
        yield {
            "type": "postgres",
            "host": str(directory),
            "port": port,
            "dbname": "postgres",
            "user": "agac",
        }
    finally:
        subprocess.run(
            _as("postgres", [str(binaries / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"]),
            check=False,
            capture_output=True,
        )
        shutil.rmtree(directory, ignore_errors=True)


@contextmanager
def mysql_server() -> Iterator[dict[str, Any] | None]:
    """Settings of a ``mysql`` connection to a MariaDB server started for the caller."""
    server = shutil.which("mariadbd") or shutil.which("mysqld")
    install = shutil.which("mariadb-install-db") or shutil.which("mysql_install_db")
    if server is None or install is None or not has_driver("pymysql"):
        yield None
        return
    directory = _server_directory("mysql")
    data, socket = directory / "data", directory / "server.sock"
    user = "mysql" if os.geteuid() == 0 else os.environ.get("USER", "root")
    process = None
    try:
        subprocess.run(
            _as(
                "mysql",
                [install, f"--datadir={data}", "--auth-root-authentication-method=normal"],
            ),
            check=True,
            capture_output=True,
        )
        process = subprocess.Popen(
            _as(
                "mysql",
                [
                    server,
                    f"--datadir={data}",
                    f"--socket={socket}",
                    f"--pid-file={directory / 'server.pid'}",
                    "--skip-networking",
                    "--skip-grant-tables",
                ],
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for(socket, process)
        import pymysql

        with pymysql.connect(unix_socket=str(socket), user="root") as connection:
            connection.cursor().execute("CREATE DATABASE agac")
    except (OSError, subprocess.SubprocessError, TimeoutError):
        if process is not None:
            process.kill()
        shutil.rmtree(directory, ignore_errors=True)
        yield None
        return
    try:
        yield {"type": "mysql", "unix_socket": str(socket), "database": "agac", "user": user}
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(directory, ignore_errors=True)


def _wait_for(socket: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _START_SECONDS
    while not socket.exists():
        if process.poll() is not None or time.monotonic() > deadline:
            raise TimeoutError(f"the server did not open {socket}")
        time.sleep(0.2)
