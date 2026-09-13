"""Marker for framework-internal log messages.

Pass as ``extra=DIAGNOSTIC`` on a ``logger`` call whose message describes how the
framework works rather than something the user can change. The console drops the
line unless the run is verbose; the log files keep it at its own level, so it is
still there when someone debugs the run.

The key is namespaced because the bridge consumes it: an unqualified name would
let an unrelated ``extra`` field silently suppress its own event.
"""

from __future__ import annotations

from typing import Any

DIAGNOSTIC_KEY = "_agac_diagnostic"
DIAGNOSTIC: dict[str, Any] = {DIAGNOSTIC_KEY: True}
