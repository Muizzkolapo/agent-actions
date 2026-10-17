"""Null namespace sentinel for a dependency namespace the record cannot supply.

``DependencyNamespaceBuilder`` puts a ``NullNamespace`` in place of a declared
dependency whose output this record does not carry, so observe/passthrough
resolve its fields to ``None`` instead of crashing. Its ``reason`` records what
the record shows about why, and :func:`diagnose` turns that into the first
sentence of the render error a prompt reading the namespace gets.
"""

from __future__ import annotations


class NullNamespace:
    """Sentinel replacing ``None`` for a namespace the record cannot supply.

    Attributes:
        reason: One of the ``REASON_*`` constants below.
        observed: For ``REASON_NO_DECLARED_FIELDS``, the fields the action observes.
        present: For ``REASON_NO_DECLARED_FIELDS``, the fields the namespace holds.
    """

    __slots__ = ("reason", "observed", "present")

    def __init__(
        self, reason: str, observed: tuple[str, ...] = (), present: tuple[str, ...] = ()
    ) -> None:
        self.reason = reason
        self.observed = observed
        self.present = present

    def _key(self) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        return (self.reason, self.observed, self.present)

    def __bool__(self) -> bool:
        """Falsy — so ``if ns_data:`` still skips null namespaces."""
        return False

    def __repr__(self) -> str:
        return f"NullNamespace(reason={self.reason!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NullNamespace):
            return self._key() == other._key()
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("NullNamespace", *self._key()))


# ── Reason constants ──────────────────────────────────────────────────
# Use these instead of bare string literals so typos are caught at import time.

# The namespace is null and the record's state history shows a guard on it skipping it.
REASON_SKIPPED = "skipped"
# The namespace is null, and the record's state history shows no guard skip by it.
REASON_NO_OUTPUT = "no_output"
# The record carries no key for the namespace at all.
REASON_ABSENT = "absent"
# The namespace holds data, but none of the fields the action observes from it.
REASON_NO_DECLARED_FIELDS = "no_declared_fields"

# ── Pre-built singletons ─────────────────────────────────────────────
# Avoids repeated allocation for the common case.

SKIPPED_NAMESPACE = NullNamespace(reason=REASON_SKIPPED)
NO_OUTPUT_NAMESPACE = NullNamespace(reason=REASON_NO_OUTPUT)
ABSENT_NAMESPACE = NullNamespace(reason=REASON_ABSENT)


def no_declared_fields_namespace(observed: list[str], present: list[str]) -> NullNamespace:
    """The sentinel for an output that holds none of the *observed* fields."""
    return NullNamespace(
        REASON_NO_DECLARED_FIELDS, observed=tuple(sorted(observed)), present=tuple(sorted(present))
    )


def is_null_namespace(value: object) -> bool:
    """Return True if *value* is a null namespace marker.

    Handles both the new ``NullNamespace`` sentinel and legacy ``None``
    (used by tests and any code that constructs field_context manually).
    """
    return value is None or isinstance(value, NullNamespace)


def diagnose(ns: str, value: object, action: str) -> str:
    """One sentence saying what the record shows about why *ns* has no data for *action*.

    A guard is named only when the record shows that guard skipping it.
    """
    reason = value.reason if isinstance(value, NullNamespace) else None
    if reason == REASON_SKIPPED:
        return f"Namespace '{ns}' is null on this record: a guard on '{ns}' skipped it."
    if reason == REASON_NO_OUTPUT:
        return (
            f"Namespace '{ns}' is null on this record: '{ns}' wrote no output for it, "
            f"and the record's state history shows no guard on '{ns}' skipping it."
        )
    if reason == REASON_ABSENT:
        return (
            f"Namespace '{ns}' is not on this record: no output of '{ns}' reached it. "
            f"Check that '{ns}' is upstream of '{action}' through its dependencies."
        )
    if reason == REASON_NO_DECLARED_FIELDS and isinstance(value, NullNamespace):
        observed = ", ".join(value.observed)
        present = ", ".join(value.present) or "no fields"
        return (
            f"Namespace '{ns}' has none of the fields '{action}' observes from it "
            f"(observes: {observed}; '{ns}' has: {present}). Check the field names in "
            f"context_scope.observe against what '{ns}' outputs."
        )
    return f"Namespace '{ns}' is null on this record."
