"""A Jinja environment where dot access on a mapping reads its key, never its attribute.

Jinja's own `Environment.getattr` tries `getattr(obj, attribute)` first and falls back to
`obj[attribute]` only on `AttributeError`, and its `getitem` falls back to the attribute
on a missing key. A dict has `items`/`keys`/`values`/`get` as real methods, so
`{{ record.items }}` would read the bound method instead of the `items` key, or, with no
such key, render the method instead of failing. Here a key the mapping lacks is undefined
under either form; one named like a method can still be called, so `record.items()` and
`record.get('x', 'd')` call the method.

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
        self.present = present

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.place, self.field, self.present))


class DictKeyFirstEnvironment(Environment):
    """Prefers a mapping's own key over an attribute of the same name."""

    def __init__(
        self, *, place_of: Callable[[Any], str | None] | None = None, **options: Any
    ) -> None:
        """*place_of* gives a mapping's dotted place in the render context, or ``None``."""
        super().__init__(**options)
        self.policies["json.dumps_function"] = deep_json.dumps
        self.place_of = place_of
        self._method_undefined: type[Undefined] | None = None

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, Mapping) and attribute in obj:
            return obj[attribute]
        return self._key_or_missing(obj, attribute, super().getattr(obj, attribute))

    def getitem(self, obj: Any, argument: Any) -> Any:
        return self._key_or_missing(obj, argument, super().getitem(obj, argument))

    def _key_or_missing(self, obj: Any, name: Any, value: Any) -> Any:
        if not isinstance(obj, Mapping) or not isinstance(name, str):
            return value
        if not isinstance(value, Undefined) and name in obj:
            return value
        # The key is missing. *value* is Jinja's undefined or, read off the mapping
        # instead, an attribute such as a dict method, which only a call may reach.
        exc = self._missing_error(obj, name)
        if isinstance(value, Undefined) or not callable(value):
            return self.undefined(obj=obj, name=name, exc=exc)  # type: ignore[arg-type]
        missing = self._method_undefined_class()(obj=obj, name=name, exc=exc)
        missing._method = value  # type: ignore[attr-defined]
        return missing

    def _missing_error(self, obj: Mapping[Any, Any], name: str) -> Any:
        place_of = self.place_of
        if place_of is None:
            return UndefinedError

        # Built only if the undefined is used, so `| default` pays no search.
        def error(message: str) -> UndefinedError:
            place = place_of(obj)
            if place is None:
                return UndefinedError(message)
            return MissingFieldError(place, name, sorted(str(key) for key in obj))

        return error

    def _method_undefined_class(self) -> type[Undefined]:
        cls = self._method_undefined
        if cls is None or cls.__base__ is not self.undefined:
            cls = self._method_undefined = _method_undefined_class(self.undefined)
        return cls


def _method_undefined_class(undefined: type[Undefined]) -> type[Undefined]:
    """*undefined*, except that calling it calls the method it stands in for."""

    class MethodOrMissing(undefined):  # type: ignore[valid-type,misc]
        __slots__ = ("_method",)
        # Read by Jinja's `Context.call`; an undefined's attribute lookup would fail.
        jinja_pass_arg = None

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self._method(*args, **kwargs)

    return MethodOrMissing
