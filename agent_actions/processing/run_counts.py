"""Per-execution counts the run line reports that no stored row total can give.

The executor opens a counter around one execution of an action; every collection
inside it adds its ``CollectionStats`` counts. Context-scoped like the token usage
tracker, so the per-file, first-stage and batch paths need not return them, and a
parallel action running in its own task or thread keeps its own counter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.processing.result_collector import CollectionStats


@dataclass
class RunCounts:
    """What one execution's collections found: guard skips (rows) and records shipped
    with a failing verdict."""

    guard_skipped: int = 0
    checks_failed: int = 0


_current: ContextVar[RunCounts | None] = ContextVar("_run_counts", default=None)


@contextmanager
def counting() -> Iterator[RunCounts]:
    """Count the collections made inside the block, and nothing collected outside it."""
    counts = RunCounts()
    token = _current.set(counts)
    try:
        yield counts
    finally:
        _current.reset(token)


def add_collection(stats: CollectionStats) -> None:
    """Add one collection's counts to the open counter; outside an execution, nothing."""
    counts = _current.get()
    if counts is None:
        return
    counts.guard_skipped += stats.guard_skipped
    counts.checks_failed += stats.checks_failed
