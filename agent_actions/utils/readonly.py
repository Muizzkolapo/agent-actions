"""Read-only views over a record, for handing to user code such as a guard UDF.

The storage holds wrappers, never the record's own containers: `dict(view)`, `{**view}`
and `xs + []` read stored values below any Python override, so the record is wrapped whole
on the way in. A write is refused, and `copy()` gives a plain writable structure with the
record's shape. One loop with a memo builds and copies (`_rebuild`): nothing recurses, each
container is replaced once, and storage is read directly, never through a subclass's
accessors. `guards/ARCHITECTURE.md` ("The read-only view") has the contract and its limits.
"""

from __future__ import annotations

from typing import Any, NoReturn

_MESSAGE = (
    "A guard's evaluation context is read-only: it is built from the record, so writing to "
    "it would be an attempt to rewrite the record mid-run. Copy what you need "
    "(data['ns'].copy(), which is deep and writable) and return a value instead of "
    "mutating the input."
)


# Exact types that hold nothing: the test almost every value in a record meets first.
_LEAVES = frozenset({str, int, float, bool, type(None)})


def _rebuild(value: Any, readonly: bool, root: Any = None) -> Any:
    """*value* with every container under it replaced: by wrappers, or by plain ones.

    *root*, when given, is the empty dict or list that stands for *value* itself.
    """
    memo: dict[int, Any] = {}
    walked: list[tuple[Any, Any]] = []
    if root is None:
        root = _child(value, memo, walked, readonly)
    else:
        _remember(value, root, memo, walked)
    # `walked` grows while it is read: a dict or list is made empty where it is first met
    # and filled here, so a reference back to it finds it and no call nests inside another.
    for made, source in walked:
        # Each source is read from its own storage and all at once. A subclass's accessors
        # are user code that can raise or build without end, and `dict.copy` asks them
        # where `__iter__` is overridden; a snapshot also cannot change size under the loop.
        if isinstance(made, dict):
            pairs = tuple(dict.items(source))
            if pairs:
                dict.update(
                    made,
                    {
                        key: item if type(item) in _LEAVES else _child(item, memo, walked, readonly)
                        for key, item in pairs
                    },
                )
        elif isinstance(made, list):
            items = list.copy(source)
            if items:
                list.extend(
                    made,
                    [
                        item if type(item) in _LEAVES else _child(item, memo, walked, readonly)
                        for item in items
                    ],
                )
    return root


def _remember(value: Any, made: Any, memo: dict[int, Any], walked: list[tuple[Any, Any]]) -> None:
    """Note that *made* replaces *value*, and keep *value* alive while the memo names it.

    An id is unique only among live objects, and a key's `__hash__` runs during the walk and
    can drop one. An entry that outlived its original would be handed to whatever was built
    next at that address.
    """
    memo[id(value)] = made
    walked.append((made, value))


def _child(value: Any, memo: dict[int, Any], walked: list[tuple[Any, Any]], readonly: bool) -> Any:
    """What replaces one value met on the walk. A dict or list is queued, not descended into."""
    made = memo.get(id(value))
    if made is not None:  # not truthiness: on a cycle the entry found is still empty
        return made
    if readonly and isinstance(value, _WRAPPERS):
        return value
    if isinstance(value, dict):
        made = dict.__new__(ReadOnlyDict) if readonly else {}
    elif isinstance(value, list):
        made = list.__new__(ReadOnlyList) if readonly else []
    elif isinstance(value, tuple):
        return _tuple(value, memo, walked, readonly)
    elif isinstance(value, set):
        # Members are hashable, so a set holds no dict or list; only the set is replaced.
        made = ReadOnlySet(value) if readonly else set(value)
    else:
        return value  # frozenset included: immutable, and its members are hashable too
    _remember(value, made, memo, walked)
    return made


def _tuple(value: Any, memo: dict[int, Any], walked: list[tuple[Any, Any]], readonly: bool) -> Any:
    """*value* with its items replaced, or *value* itself where none of them needed it.

    A tuple cannot be made empty and filled later, so it is built when met. The only descent
    that needs is into tuples nested directly in tuples -- a dict or list among the items is
    queued -- and those are built innermost first on a stack of their own.
    """
    stack: list[tuple[Any, list[Any], Any]] = [(value, [], tuple.__iter__(value))]
    unfinished = {id(value)}
    while True:
        source, built, items = stack[-1]
        for item in items:
            if isinstance(item, tuple) and id(item) not in memo:
                if id(item) in unfinished:
                    raise ValueError("a tuple that contains itself cannot be rebuilt")
                unfinished.add(id(item))
                stack.append((item, [], tuple.__iter__(item)))
                break
            built.append(item if type(item) in _LEAVES else _child(item, memo, walked, readonly))
        else:
            stack.pop()
            unchanged = all(
                new is old for new, old in zip(built, tuple.__iter__(source), strict=True)
            )
            made = source if unchanged else tuple(built)
            _remember(source, made, memo, walked)
            if not stack:
                return made
            stack[-1][1].append(made)


def _refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise TypeError(_MESSAGE)


class ReadOnlyDict(dict):
    """A dict that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), /) -> None:
        _rebuild(source if isinstance(source, dict) else dict(source), True, self)

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

    def get(self, key: Any, default: Any = None) -> Any:
        # `dict.get` takes `default` positionally only, and a UDF passing it by keyword
        # must not raise: a guard whose UDF raises passes its record.
        return dict.get(self, key, default)

    def values(self):  # type: ignore[misc]
        return list(dict.values(self))

    def items(self):  # type: ignore[misc]
        return list(dict.items(self))

    def copy(self) -> dict:
        """A real, writable dict, deep -- the documented way to take what you need.

        Deep because this is what `_MESSAGE` tells a UDF author to call: a shallow copy
        shares the view's nested wrappers, so a write one level down would be refused on
        the very thing the author was told to take.
        """
        plain: dict[Any, Any] = _rebuild(self, False)
        return plain

    def __copy__(self) -> dict:
        # `copy.copy` rebuilds a dict subclass by assigning into a fresh instance, which
        # `__setitem__` refuses -- so without this the author is told to copy and cannot.
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> dict:
        return self.copy()


class ReadOnlyList(list):
    """A list that refuses mutation and holds its nested containers already wrapped."""

    def __init__(self, source: Any = (), /) -> None:
        _rebuild(source if isinstance(source, list) else list(source), True, self)

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

    def copy(self) -> list:
        """A real, writable list, deep -- as on ReadOnlyDict."""
        plain: list[Any] = _rebuild(self, False)
        return plain

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


_WRAPPERS = (ReadOnlyDict, ReadOnlyList, ReadOnlySet)


def readonly_view(data: Any) -> Any:
    """A read-only view of *data*, safe to hand to user code."""
    return _rebuild(data, True)


__all__ = ["ReadOnlyDict", "ReadOnlyList", "readonly_view"]
