"""Read-only views over a record, for handing to user code such as a guard UDF.

Wrapped on the way in: `dict(view)`, `{**view}`, `xs + []` and `reversed(xs)` read stored
values below any Python override, so the storage must already hold wrappers. A write is
refused loudly so a UDF never believes it took effect; `copy()` is the hatch, plain, deep
and writable. Subclassing dict/list/set keeps `isinstance`, `json.dumps` and `**` working.
The view is a snapshot of the record's structure when built. Both walks memoise each
container by `id()`, as `copy.deepcopy` does, so a cycle terminates and a shared dict, list
or set stays one object; a tuple read from a view is rebuilt each time.
"""

from __future__ import annotations

from typing import Any, NoReturn

_MESSAGE = (
    "A guard's evaluation context is read-only: it is built from the record, so writing to "
    "it would be an attempt to rewrite the record mid-run. Copy what you need "
    "(data['ns'].copy(), which is deep and writable) and return a value instead of "
    "mutating the input."
)


def _hold(memo: dict[int, Any], built: Any) -> None:
    # The memo keys `id()`, unique only while its object lives. The walk runs user code (a
    # subclass accessor, a key's `__hash__`) that can build values or drop the record's own,
    # so everything a container yields is kept alive until the walk ends.
    memo.setdefault(id(memo), []).append(built)


def _readonly(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """Wrap *value* if it is a container, so a write through it cannot reach the record.

    *memo* maps `id(container)` to its wrapper for one walk.
    """
    if isinstance(value, _WRAPPERS):
        return value
    if not isinstance(value, _WRAPPABLE):
        return value
    if memo is None:
        memo = {}
    elif (wrapped := memo.get(id(value))) is not None:
        return wrapped
    if isinstance(value, dict):
        return ReadOnlyDict(value, memo)
    if isinstance(value, list):
        return ReadOnlyList(value, memo)
    if isinstance(value, tuple):
        # Not memoisable before its items exist, so a reference back into a tuple re-walks
        # it: 29 nested tuples that each hold one back to the outermost exhaust the stack.
        # A record read from JSON holds no tuples.
        items = tuple(value)
        _hold(memo, items)
        return memo.setdefault(id(value), tuple(_readonly(item, memo) for item in items))
    # Set members are hashable, so a set holds no plain dict or list and its members are not
    # walked; only the set itself is guarded. frozenset needs nothing.
    return memo.setdefault(id(value), ReadOnlySet(value))


def _unwrap(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """A plain, writable copy of *value*; set members, being hashable, are kept by reference.

    Memoised for the same reason as `_readonly`: once construction stops raising on a cycle,
    this is the next walk that would recurse forever on one.
    """
    if not isinstance(value, _COPYABLE):
        return value
    if memo is None:
        memo = {}
    elif (done := memo.get(id(value))) is not None:
        return done
    if isinstance(value, dict):
        plain: dict[Any, Any] = {}
        memo[id(value)] = plain
        for key in value:
            plain[key] = _unwrap(dict.__getitem__(value, key), memo)
        return plain
    if isinstance(value, list):
        items: list[Any] = []
        memo[id(value)] = items
        items.extend(_unwrap(item, memo) for item in list.__iter__(value))
        return items
    if isinstance(value, tuple):
        return memo.setdefault(id(value), tuple(_unwrap(item, memo) for item in value))
    if isinstance(value, frozenset):
        # `frozenset(x)` is x itself for an exact frozenset; for a subclass it is a new
        # object, and the memo is what keeps one shared instance one object in the copy.
        return memo.setdefault(id(value), frozenset(value))
    return memo.setdefault(id(value), set(set.__iter__(value)))


def _refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise TypeError(_MESSAGE)


class ReadOnlyDict(dict):
    """A dict that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), memo: dict[int, Any] | None = None, /) -> None:
        # Wrapped on the way IN, not on the way out. `dict(view)` and `{**view}` copy the
        # values as stored through a C fast path that no Python override sees, so storing
        # the record's own containers handed them straight back (measured). Storing
        # wrappers means such a copy carries wrappers, and a nested write through it is
        # refused instead of silently rewriting the record.
        memo = {} if memo is None else memo
        # Registered before the values are walked, so a cycle leading back to *source*
        # resolves to this instance -- empty at that moment, populated before any read.
        memo[id(source)] = self
        items = dict(source)
        _hold(memo, items)
        super().__init__({key: _readonly(value, memo) for key, value in items.items()})

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
        plain: dict[Any, Any] = _unwrap(self)
        return plain

    def __copy__(self) -> dict:
        # `copy.copy` rebuilds a dict subclass by assigning into a fresh instance, which
        # `__setitem__` refuses -- so without this the author is told to copy and cannot.
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> dict:
        return self.copy()


class ReadOnlyList(list):
    """A list that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), memo: dict[int, Any] | None = None, /) -> None:
        # Wrapped on the way in, for the reason given on ReadOnlyDict: `xs + []` and
        # `reversed(xs)` read the items as stored, below any Python override.
        memo = {} if memo is None else memo
        memo[id(source)] = self
        items = list(source)
        _hold(memo, items)
        super().__init__(_readonly(item, memo) for item in items)

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
        items: list[Any] = _unwrap(self)
        return items

    def __copy__(self) -> list:
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> list:
        return self.copy()


class ReadOnlySet(set):
    """A set that refuses mutation.

    Members only -- a set's members must be hashable, so it cannot hold a dict or a list,
    and there is nothing below it to wrap. `frozenset` needs no wrapper at all.
    """

    def __iand__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        # In-place operators again: refused explicitly because the C-level slot does not
        # route through the named-method overrides below.
        _refuse()

    def __ior__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        _refuse()

    def __isub__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        _refuse()

    def __ixor__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        _refuse()

    def add(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def difference_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def discard(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def intersection_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def remove(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def symmetric_difference_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def copy(self) -> set:  # type: ignore[override]
        """A real, writable set."""
        return set(set.__iter__(self))

    def __copy__(self) -> set:
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> set:
        return self.copy()


# Tuples, not `A | B`: that builds a types.UnionType per call, once per value in the record.
_WRAPPERS = (ReadOnlyDict, ReadOnlyList, ReadOnlySet)
_WRAPPABLE = (dict, list, tuple, set)  # frozenset is absent: immutable, members not walked
_COPYABLE = (*_WRAPPABLE, frozenset)


def readonly_view(data: Any) -> Any:
    """A read-only view of *data*, safe to hand to user code."""
    return _readonly(data)


__all__ = ["ReadOnlyDict", "ReadOnlyList", "readonly_view"]
