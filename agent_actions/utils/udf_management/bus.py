"""Bus: the namespace dict passed to RECORD-mode UDFs, with a strict accessor."""

from __future__ import annotations

from typing import Any

from agent_actions.utils.readonly import ReadOnlyDict


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


class ReadOnlyBus(ReadOnlyDict, Bus):
    """A Bus that is a read-only view, for the guard-clause path.

    A Bus, so `execute_user_defined_function` passes it through rather than re-wrapping
    it in a plain Bus with a writable top level. A ReadOnlyDict, so the top level refuses
    writes and stores wrappers exactly as every level below it does.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # The context itself where one dict was given, so a reference back to it inside
        # the record is the bus and not a second view of its top level.
        given = len(args) == 1 and not kwargs and isinstance(args[0], dict)
        super().__init__(args[0] if given else dict(*args, **kwargs))
