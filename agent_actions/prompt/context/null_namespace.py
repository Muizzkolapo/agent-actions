"""Null namespace sentinel for skipped/filtered upstream actions.

When a guard skips or filters an upstream action, the downstream record's
content contains ``{action_name: None}``.  At the ``DependencyNamespaceBuilder``
layer we wrap that ``None`` in a ``NullNamespace`` so downstream code can
distinguish *why* the namespace is absent and resolve observe/passthrough
fields to ``None`` instead of crashing.

Phase 9b introduces the sentinel for guard-skipped namespaces.
Phase 9c will extend it for guard-filtered namespaces.
"""

from __future__ import annotations


class NullNamespace:
    """Sentinel replacing ``None`` for a namespace that was intentionally absent.

    Attributes:
        reason: Why the namespace is null (e.g. ``"skipped"``, ``"filtered"``).
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __bool__(self) -> bool:
        """Falsy — so ``if ns_data:`` still skips null namespaces."""
        return False

    def __str__(self) -> str:
        return f"None ({self.reason})"

    def __repr__(self) -> str:
        return f"NullNamespace(reason={self.reason!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NullNamespace):
            return self.reason == other.reason
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("NullNamespace", self.reason))


# ── Reason constants ──────────────────────────────────────────────────
# Use these instead of bare string literals so typos are caught at import time.

REASON_SKIPPED = "skipped"
REASON_FILTERED = "filtered"

# ── Pre-built singletons ─────────────────────────────────────────────
# Avoids repeated allocation for the common case.

SKIPPED_NAMESPACE = NullNamespace(reason=REASON_SKIPPED)


def is_null_namespace(value: object) -> bool:
    """Return True if *value* is a null namespace marker.

    Handles both the new ``NullNamespace`` sentinel and legacy ``None``
    (used by tests and any code that constructs field_context manually).
    """
    return value is None or isinstance(value, NullNamespace)
