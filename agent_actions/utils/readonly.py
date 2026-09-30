"""Read-only views over a record, for handing to user code.

Guard evaluation assembles its context by assigning the record's namespaces by reference,
so the dict a `conditional_clause` UDF receives IS the record's own content. A UDF that
writes to it rewrites the record mid-run, and everything downstream -- the action's input,
the enricher, the skipped tombstones -- sees the rewritten value with nothing logged.

Two separate things are going on, and it is worth being exact about which does what:

* **Wrapping on access is what protects the record.** Each access returns a fresh wrapper
  constructed from the underlying container, so a write lands on that copy and never
  reaches the record -- at any depth, because every level is re-wrapped. Returning the raw
  value anywhere reopens the hole, which is why `items`, `values` and list iteration are
  overridden too.
* **Refusing mutation is what makes it honest.** Without it a UDF's write would silently
  succeed against a copy and the author would believe it had taken effect. Raising names
  the offending UDF instead.

These are dict/list subclasses rather than MappingProxyType or a bare Mapping so that
`isinstance(x, dict)`, `json.dumps(x)` and `**x` keep working for the overwhelming
majority of UDFs, which only read.
"""

from __future__ import annotations

from typing import Any, NoReturn

_MESSAGE = (
    "A guard's evaluation context is read-only: it holds the record's own namespaces by "
    "reference, so writing to it would rewrite the record mid-run. Copy what you need "
    "(e.g. dict(data['ns'])) and return a value instead of mutating the input."
)


def _readonly(value: Any) -> Any:
    """Wrap *value* if it is a container, so a write through it cannot reach the record."""
    if isinstance(value, ReadOnlyDict | ReadOnlyList):
        return value
    if isinstance(value, dict):
        return ReadOnlyDict(value)
    if isinstance(value, list):
        return ReadOnlyList(value)
    return value


def _refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise TypeError(_MESSAGE)


class ReadOnlyDict(dict):
    """A dict that refuses mutation and wraps nested containers on the way out."""

    def __setitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __delitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __ior__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        # Kept despite `update` being refused: measured, the C-level in-place operator
        # does NOT route through the Python override -- with only `update` overridden,
        # `view |= {...}` mutates the view in place and reports success.
        _refuse()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def popitem(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def setdefault(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __getitem__(self, key: Any) -> Any:
        return _readonly(dict.__getitem__(self, key))

    def get(self, key: Any, default: Any = None) -> Any:
        if key not in self:
            return default
        return self[key]

    def values(self):  # type: ignore[misc]
        return [self[key] for key in self]

    def items(self):  # type: ignore[misc]
        return [(key, self[key]) for key in self]

    def copy(self) -> dict:
        """A real, writable dict -- the documented way to take what you need."""
        return {key: dict.__getitem__(self, key) for key in self}


class ReadOnlyList(list):
    """A list that refuses mutation and wraps nested containers on the way out."""

    def __setitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __delitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __iadd__(self, other: Any) -> NoReturn:  # type: ignore[misc,override]
        # As above: `lst += [...]` bypasses the `extend` override at C level. The ignore
        # is unavoidable -- an in-place operator that REFUSES cannot have a return type
        # compatible with its binary counterpart, which returns a new list.
        _refuse()

    def __imul__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        _refuse()

    def append(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def extend(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def insert(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def remove(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def reverse(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def sort(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def __getitem__(self, index: Any) -> Any:
        return _readonly(list.__getitem__(self, index))

    def __iter__(self):
        return (_readonly(item) for item in list.__iter__(self))

    def copy(self) -> list:
        return [list.__getitem__(self, i) for i in range(len(self))]


def readonly_view(data: Any) -> Any:
    """A read-only view of *data*, safe to hand to user code."""
    return _readonly(data)


__all__ = ["ReadOnlyDict", "ReadOnlyList", "readonly_view"]
