"""Marker for framework-internal log messages.

Pass as ``extra=DIAGNOSTIC`` on a ``logger`` call whose message describes
framework internals -- namespace shapes, index bounds, node ids. The console
drops the line unless the run is verbose; the log files keep it at its own
level, so the message is still there when someone debugs the run.
"""

from __future__ import annotations

from typing import Any

DIAGNOSTIC_KEY = "diagnostic"
DIAGNOSTIC: dict[str, Any] = {DIAGNOSTIC_KEY: True}
