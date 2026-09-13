"""Marker for framework-internal log messages.

Pass as ``extra=DIAGNOSTIC`` when the person running the workflow cannot change
what the message describes; anything their config, prompt, schema or tool code
produced stays on the console. Marked lines are dropped by the console unless
the run is verbose, and kept by the log files at their own level.

The key is namespaced because the bridge consumes it: an unqualified name would
let an unrelated ``extra`` field silently suppress its own event.
"""

from __future__ import annotations

from typing import Any

DIAGNOSTIC_KEY = "_agac_diagnostic"
DIAGNOSTIC: dict[str, Any] = {DIAGNOSTIC_KEY: True}
