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

    A Bus subclass, not a separate wrapper, because `execute_user_defined_function`
    re-wraps any plain dict in a Bus -- `Bus(view)` reads the underlying storage and
    hands the UDF the record's own nested dicts again, silently undoing the guard.
    Being a Bus already, this passes through untouched and keeps `require()`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from agent_actions.utils.readonly import ReadOnlyDict

        super().__init__(*args, **kwargs)
        self._readonly = ReadOnlyDict(self)

    def __getitem__(self, key: str) -> Any:
        return self._readonly[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._readonly.get(key, default)

    def values(self):  # type: ignore[override]
        return self._readonly.values()

    def items(self):  # type: ignore[override]
        return self._readonly.items()

    def _refuse(self, *args: Any, **kwargs: Any) -> NoReturn:
        from agent_actions.utils.readonly import _MESSAGE

        raise TypeError(_MESSAGE)

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
