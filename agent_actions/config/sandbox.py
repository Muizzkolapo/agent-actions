"""Sandbox runs: the offline mock answers every LLM action, and the output is kept apart.

A command given ``--sandbox`` sets the mode for the whole process with ``sandbox_mode``.
Each path a run writes or a read command reads is derived here, so a sandbox run never
writes where a real run reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent_actions.utils.constants import DEFAULT_ACTION_KIND, MODEL_VENDOR_KEY

SANDBOX_VENDOR = "agac-provider"
SANDBOX_DIR = "sandbox"
STATUS_FILE_NAME = ".agent_status.json"
SANDBOX_STORE_SUFFIX = ".sandbox.db"
# Set on a HITL action's config: the review approves every record with no human.
AUTO_APPROVE_KEY = "_sandbox_auto_approve"

_active = False


def is_active() -> bool:
    return _active


@contextmanager
def sandbox_mode(enabled: bool) -> Iterator[None]:
    global _active
    previous = _active
    _active = enabled
    try:
        yield
    finally:
        _active = previous


def flag() -> str:
    """The flag a printed command needs to act on this run's output: ``" --sandbox"`` or ``""``."""
    return " --sandbox" if _active else ""


def run_dir(io_dir: Path) -> Path:
    """The folder that holds a run's ``target/``, ``logs/`` and status file."""
    return io_dir / SANDBOX_DIR if _active else io_dir


def status_file(io_dir: Path) -> Path:
    return run_dir(io_dir) / STATUS_FILE_NAME


def store_file(io_dir: Path, workflow_name: str) -> Path:
    suffix = SANDBOX_STORE_SUFFIX if _active else ".db"
    return io_dir / "store" / f"{workflow_name}{suffix}"


def is_sandbox_store(path: Path) -> bool:
    """True when *path* is a store ``store_file`` names for a sandbox run."""
    return path.name.endswith(SANDBOX_STORE_SUFFIX)


def point_at_mock(action_configs: dict[str, dict[str, Any]]) -> list[str]:
    """Send each LLM action to the mock and approve each HITL review; returns the LLM actions.

    The model name stays, for display. Tool actions and the other kinds are left as they are.
    """
    mocked = []
    for name, config in action_configs.items():
        kind = config.get("kind") or DEFAULT_ACTION_KIND
        kind = getattr(kind, "value", kind)
        if kind == DEFAULT_ACTION_KIND:
            config[MODEL_VENDOR_KEY] = SANDBOX_VENDOR
            mocked.append(name)
        elif kind == "hitl":
            config[AUTO_APPROVE_KEY] = True
    return mocked
