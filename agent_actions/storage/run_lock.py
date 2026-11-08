"""One run per workflow: an advisory file lock held for the whole command."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import portalocker

from agent_actions.errors import RunInProgressError


def run_lock_path(io_dir: Path, workflow_name: str) -> Path:
    """The lock file, beside the database `get_storage_backend` opens."""
    return io_dir / "store" / f"{workflow_name}.db.lock"


@contextmanager
def hold_run_lock(io_dir: Path, workflow_name: str) -> Iterator[None]:
    """Hold *workflow_name*'s run lock for the block, or raise `RunInProgressError` at once.

    The operating system releases the lock when the holder exits, however it exits, so a
    killed run leaves no lock behind. The holder's pid in the file only names it.
    """
    path = run_lock_path(io_dir, workflow_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.LockException:
            pid = _holder_pid(path)
            held_by = f" (pid {pid})" if pid else ""
            # Not chained: the user-error frame names the innermost cause, and contention
            # is the expected state here, not an OS fault.
            raise RunInProgressError(
                f"Another run of workflow '{workflow_name}' is in progress{held_by}. "
                "Wait for it to finish or stop it, then run again.",
                context={"workflow": workflow_name, "lock_file": str(path), "pid": pid},
            ) from None
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            yield
        finally:
            # Cleared first, so a refusal never names a holder that has gone.
            handle.seek(0)
            handle.truncate()
            handle.flush()
            portalocker.unlock(handle)


def _holder_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None
