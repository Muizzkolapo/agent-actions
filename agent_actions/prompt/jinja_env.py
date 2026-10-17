"""A Jinja environment where dot access on a mapping reads its key before its attribute.

Jinja's own `Environment.getattr` tries `getattr(obj, attribute)` first and falls back to
`obj[attribute]` only on `AttributeError`. A dict has `items`/`keys`/`values`/`get` as real
methods, so `{{ record.items }}` silently returns the bound method instead of the `items`
key -- no error, no undefined, just the wrong value sent to the model or iterated downstream.

`| tojson` encodes through `deep_json`, so it renders a value nested past the C JSON
encoder's recursion limit too, with the same text.

Jinja's error for a key a mapping lacks names only the key ("'dict object' has no
attribute 'x'"). Given `place_of`, the error names where the mapping sits too, as a
`MissingFieldError`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from jinja2 import Environment, Undefined, UndefinedError

from agent_actions.utils import deep_json

_FIELDS_SHOWN = 10


class MissingFieldError(UndefinedError):
    """A template read a field the mapping at ``place`` does not have."""

    def __init__(self, place: str, field: str, present: list[str]) -> None:
        shown = ", ".join(present[:_FIELDS_SHOWN]) or "no fields"
        if len(present) > _FIELDS_SHOWN:
            shown += f", ... (+{len(present) - _FIELDS_SHOWN} more)"
        super().__init__(f"'{place}' has no field '{field}' (it has: {shown})")
        self.place = place
        self.field = field


class DictKeyFirstEnvironment(Environment):
    """Prefers a mapping's own key over an attribute of the same name."""

    def __init__(
        self, *, place_of: Callable[[Any], str | None] | None = None, **options: Any
    ) -> None:
        """*place_of* gives a mapping's dotted place in the render context, or ``None``."""
        super().__init__(**options)
        self.policies["json.dumps_function"] = deep_json.dumps
        self.place_of = place_of

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, Mapping) and attribute in obj:
            return obj[attribute]
        return self._name_missing(obj, attribute, super().getattr(obj, attribute))

    def getitem(self, obj: Any, argument: Any) -> Any:
        return self._name_missing(obj, argument, super().getitem(obj, argument))

    def _name_missing(self, obj: Any, name: Any, value: Any) -> Any:
        place_of = self.place_of
        if (
            place_of is None
            or not isinstance(value, Undefined)
            or not isinstance(obj, Mapping)
            or not isinstance(name, str)
        ):
            return value

        # Built only if the undefined is used, so `| default` pays no search.
        def error(message: str) -> UndefinedError:
            place = place_of(obj)
            if place is None:
                return UndefinedError(message)
            return MissingFieldError(place, name, sorted(str(key) for key in obj))

        return self.undefined(obj=obj, name=name, exc=error)  # type: ignore[arg-type]
