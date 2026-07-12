"""Bus: the namespace dict passed to RECORD-mode UDFs, with a strict accessor."""

from __future__ import annotations

from typing import Any


class Bus(dict[str, Any]):
    """Action-name-keyed bus. `get`/`[]` stay tolerant; `require` raises on unknown."""

    def require(self, namespace: str) -> Any:
        if namespace not in self:
            raise KeyError(
                f"UDF read unknown bus namespace '{namespace}'. The bus is keyed by "
                f"action name; available: {sorted(self.keys())}. Check for an "
                f"impl-name/action-name mismatch."
            )
        return self[namespace]
