"""Advisory file lock for ``agac run`` to prevent concurrent double-execute.

See VIOL-0045 (UAT Round 5B). SQLite's WAL mode keeps two parallel writers from
corrupting the database, but nothing above it stops both runs from doing all the
(paid) LLM work and having the later writer win. This module adds the missing
concurrency control: a cooperative advisory lock on a sidecar file next to the
workflow's SQLite database.

The lock is *advisory* — only ``agac run`` acquires it. Read-only commands
(``inspect``, ``status``, ``list``) do not, so they are never blocked. It is
*non-blocking*: a second run fails fast with :class:`WorkflowLockHeld` rather
than hanging. The OS releases the lock automatically when the holding process
dies, so a killed run cannot leave it stuck.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import msvcrt
else:
    import fcntl


class WorkflowLockHeld(RuntimeError):
    """Raised when another ``agac run`` already holds the workflow lock."""

    def __init__(self, pid: int | None, lock_path: Path):
        self.pid = pid
        self.lock_path = lock_path
        pid_str = str(pid) if pid is not None else "unknown"
        super().__init__(
            f"Another `agac run` is already executing this workflow "
            f"(pid {pid_str}). Pass `--force` to override (not recommended)."
        )


def _read_pid(lock_path: Path) -> int | None:
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _try_lock_posix(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _release_lock_posix(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _try_lock_windows(fd: int) -> bool:
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _release_lock_windows(fd: int) -> None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextlib.contextmanager
def workflow_lock(store_dir: Path, workflow_name: str) -> Iterator[Path]:
    """Hold an exclusive non-blocking advisory lock for ``workflow_name``.

    The lock file is ``{store_dir}/{workflow_name}.db.lock`` — alongside the
    SQLite database, so it shares the database's mount and cannot collide across
    projects. Raises :class:`WorkflowLockHeld` on contention (the body carries
    the prior holder's pid for the diagnostic message).
    """
    store_dir.mkdir(parents=True, exist_ok=True)
    lock_path = store_dir / f"{workflow_name}.db.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    acquired = _try_lock_windows(fd) if IS_WINDOWS else _try_lock_posix(fd)
    if not acquired:
        prior_pid = _read_pid(lock_path)
        os.close(fd)
        raise WorkflowLockHeld(prior_pid, lock_path)
    try:
        # Stamp our pid into the body so a contending run can name us.
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.fsync(fd)
        yield lock_path
    finally:
        if IS_WINDOWS:
            _release_lock_windows(fd)
        else:
            _release_lock_posix(fd)
        os.close(fd)
