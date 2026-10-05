"""Bus: the namespace dict passed to RECORD-mode UDFs, with a strict accessor."""

from __future__ import annotations

from typing import Any, NoReturn


class Bus(dict[str, Any]):
    """Strict-accessor dict for UDF input. `get`/`[]` stay tolerant; `require` raises on unknown."""

    def require(self, namespace: str) -> Any:
        # Message stays generic: the same accessor wraps the action-keyed tool
        # bus and the flat guard-clause context, so it names the key + the
        # available keys and does not assume an action-name keying.
        if namespace not in self:
            raise KeyError(
                f"UDF read unknown key '{namespace}'. Available keys: {sorted(self.keys())}."
            )
        return self[namespace]


class ReadOnlyBus(Bus):
    """A Bus that refuses mutation, for the guard-clause path.

    A Bus, so `execute_user_defined_function` passes it through rather than re-wrapping
    it in a plain Bus with a writable top level. Its storage holds read-only wrappers:
    `dict(bus)`, `{**bus}`, `bus | {}` and the unbound `dict` methods read storage
    without calling `__getitem__`, so wrapping only on access handed the record out.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from agent_actions.utils.readonly import ReadOnlyDict

        super().__init__(ReadOnlyDict(dict(*args, **kwargs)))

    def get(self, key: str, default: Any = None) -> Any:
        # `dict.get` takes `default` positionally only; `ReadOnlyDict.get` takes it by
        # keyword, and a guard UDF that passes it that way must not raise.
        return super().get(key, default)

    def values(self):  # type: ignore[override]
        # Lists, as on ReadOnlyDict; the storage already holds the wrappers.
        return list(super().values())

    def items(self):  # type: ignore[override]
        return list(super().items())

    def copy(self) -> dict[str, Any]:
        """A plain, deep, writable dict: the hatch a namespace's own `copy()` offers."""
        from agent_actions.utils.readonly import ReadOnlyDict

        return ReadOnlyDict(self).copy()

    def __copy__(self) -> dict[str, Any]:
        # `copy.copy` rebuilds a dict subclass by assigning into a fresh instance, which
        # `__setitem__` refuses.
        return self.copy()

    def __deepcopy__(self, _memo: dict) -> dict[str, Any]:
        return self.copy()

    def __ior__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        # `bus |= {...}` merges at C level and never reaches the `update` override.
        self._refuse()

    def _refuse(self, *args: Any, **kwargs: Any) -> NoReturn:
        from agent_actions.utils.readonly import _MESSAGE, ReadOnlyError

        raise ReadOnlyError(_MESSAGE)

    def __setitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def __delitem__(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def clear(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def pop(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def popitem(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def setdefault(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._refuse()
