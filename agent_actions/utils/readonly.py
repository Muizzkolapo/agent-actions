"""Read-only views over a record, for handing to user code.

Guard evaluation assembles its context by assigning the record's namespaces by reference,
so the dict a `conditional_clause` UDF receives IS the record's own content. A UDF that
writes to it rewrites the record mid-run, and everything downstream -- the action's input,
the enricher, the skipped tombstones -- sees the rewritten value with nothing logged.

Two separate things are going on, and it is worth being exact about which does what:

* **Wrapping on the way IN is what protects the record.** The storage holds wrappers, not
  the record's own containers, so a write lands on a wrapper and never reaches the record
  at any depth. It has to be on the way in: `dict(view)`, `{**view}` and `list(view)` copy
  the values as stored through a C fast path that no Python override intercepts, so
  wrapping only on access handed the record's nested containers straight back out.
  Accessors still wrap, so a container reaching the storage unwrapped is also covered,
  which is why `items`, `values` and list iteration are overridden too.
* **Refusing mutation is what makes it honest.** Without it a UDF's write would silently
  succeed against a copy and the author would believe it had taken effect. Raising names
  the offending UDF instead.
* **Taking a copy has to work.** `copy()`, `copy.copy` and `copy.deepcopy` all return a
  plain, deep, writable structure. A shallow copy would share the record's nested
  containers, so the hatch offered to avoid rewriting the record would have rewritten it;
  `copy.copy` raised outright, because rebuilding a dict subclass assigns into a fresh
  instance and `__setitem__` refuses.

These are dict/list subclasses rather than MappingProxyType or a bare Mapping so that
`isinstance(x, dict)`, `json.dumps(x)` and `**x` keep working for the overwhelming
majority of UDFs, which only read.
"""

from __future__ import annotations

from typing import Any, NoReturn

_MESSAGE = (
    "A guard's evaluation context is read-only: it holds the record's own namespaces by "
    "reference, so writing to it would rewrite the record mid-run. Copy what you need "
    "(data['ns'].copy(), which is deep and writable) and return a value instead of "
    "mutating the input."
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


def _unwrap(value: Any) -> Any:
    """A plain, writable copy of *value*, sharing nothing with the record."""
    if isinstance(value, dict):
        return {key: _unwrap(dict.__getitem__(value, key)) for key in value}
    if isinstance(value, list):
        return [_unwrap(item) for item in list.__iter__(value)]
    return value


def _refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise TypeError(_MESSAGE)


class ReadOnlyDict(dict):
    """A dict that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), /) -> None:
        # Wrapped on the way IN, not on the way out. `dict(view)` and `{**view}` copy the
        # values as stored through a C fast path that no Python override sees, so storing
        # the record's own containers handed them straight back (measured). Storing
        # wrappers means such a copy carries wrappers, and a nested write through it is
        # refused instead of silently rewriting the record.
        super().__init__({key: _readonly(value) for key, value in dict(source).items()})

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
        """A real, writable dict, deep -- the documented way to take what you need.

        Deep because this is what `_MESSAGE` tells a UDF author to call: a shallow copy
        shares the record's nested containers, so a write one level down reached the
        record through the very hatch offered to avoid that.
        """
        return {key: _unwrap(dict.__getitem__(self, key)) for key in self}

    def __copy__(self) -> dict:
        # `copy.copy` rebuilds a dict subclass by assigning into a fresh instance, which
        # `__setitem__` refuses -- so without this the author is told to copy and cannot.
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> dict:
        return self.copy()


class ReadOnlyList(list):
    """A list that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), /) -> None:
        # Wrapped on the way in, for the reason given on ReadOnlyDict: `list(view)` and
        # `[*view]` copy the items as stored, below any Python override.
        super().__init__(_readonly(item) for item in list(source))

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
        """A real, writable list, deep -- as on ReadOnlyDict."""
        return [_unwrap(item) for item in list.__iter__(self)]

    def __copy__(self) -> list:
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> list:
        return self.copy()


def readonly_view(data: Any) -> Any:
    """A read-only view of *data*, safe to hand to user code."""
    return _readonly(data)


__all__ = ["ReadOnlyDict", "ReadOnlyList", "readonly_view"]
