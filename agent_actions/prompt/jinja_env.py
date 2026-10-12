"""A Jinja environment where dot access on a mapping reads its key before its attribute.

Jinja's own `Environment.getattr` tries `getattr(obj, attribute)` first and falls back to
`obj[attribute]` only on `AttributeError`. A dict has `items`/`keys`/`values`/`get` as real
methods, so `{{ record.items }}` silently returns the bound method instead of the `items`
key -- no error, no undefined, just the wrong value sent to the model or iterated downstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jinja2 import Environment


class DictKeyFirstEnvironment(Environment):
    """Prefers a mapping's own key over an attribute of the same name."""

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, Mapping) and attribute in obj:
            return obj[attribute]
        return super().getattr(obj, attribute)
