"""``json.loads`` / ``json.dumps`` with no nesting-depth limit.

The C codec recurses once per nesting level and raises ``RecursionError`` about 1000 levels
down on Python 3.11. Each function here tries the C codec first and, only on that error,
redoes the work on an explicit stack, producing exactly what the C codec would have.
"""

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from json.decoder import JSONDecodeError
from json.encoder import encode_basestring, encode_basestring_ascii
from json.scanner import NUMBER_RE
from typing import Any

_WHITESPACE = re.compile(r"[ \t\n\r]*")
# The decoder's own string scanner (C when available); typeshed does not declare it.
_scanstring: Callable[[str, int, bool], tuple[str, int]] = json.decoder.scanstring  # type: ignore[attr-defined]


def loads(text: str | bytes | bytearray) -> Any:
    """``json.loads(text)``, for a document nested deeper than the C decoder can go."""
    try:
        return json.loads(text)
    except RecursionError:
        if isinstance(text, (bytes, bytearray)):
            text = text.decode(json.detect_encoding(text), "surrogatepass")
        return _loads_without_recursion(text)


def dumps(
    obj: Any,
    *,
    ensure_ascii: bool = True,
    sort_keys: bool = False,
    default: Callable[[Any], Any] | None = None,
    indent: int | str | None = None,
) -> str:
    """``json.dumps`` with these options, for a value nested deeper than the C encoder can go."""
    try:
        return json.dumps(
            obj, ensure_ascii=ensure_ascii, sort_keys=sort_keys, default=default, indent=indent
        )
    except RecursionError:
        return _dumps_without_recursion(
            obj, ensure_ascii=ensure_ascii, sort_keys=sort_keys, default=default, indent=indent
        )


def nesting_depth(obj: Any) -> int:
    """How many dicts, lists and tuples deep *obj* goes; a scalar is 0."""
    deepest = 0
    seen: set[int] = set()
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (Mapping, list, tuple)):
            if id(value) in seen:
                continue
            seen.add(id(value))
        if isinstance(value, Mapping):
            children: Iterable[Any] = value.values()
        elif isinstance(value, (list, tuple)):
            children = value
        else:
            deepest = max(deepest, depth)
            continue
        deepest = max(deepest, depth + 1)
        stack.extend((child, depth + 1) for child in children)
    return deepest


def _dumps_without_recursion(
    obj: Any,
    *,
    ensure_ascii: bool,
    sort_keys: bool,
    default: Callable[[Any], Any] | None,
    indent: int | str | None = None,
) -> str:
    encode_str = encode_basestring_ascii if ensure_ascii else encode_basestring
    if indent is None:
        item_separator, step = ", ", None
    else:
        item_separator, step = ",", indent if isinstance(indent, str) else " " * indent
    parts: list[str] = []
    open_containers: set[int] = set()
    stack: list[tuple[Iterator[tuple[str, Any]], str, int]] = [(iter((("", obj),)), "", -1)]
    while stack:
        members, closer, marker = stack[-1]
        for prefix, value in members:
            parts.append(prefix)
            converted: set[int] = set()
            while True:
                if value is None:
                    parts.append("null")
                elif value is True:
                    parts.append("true")
                elif value is False:
                    parts.append("false")
                elif isinstance(value, str):
                    parts.append(encode_str(value))
                elif isinstance(value, int):
                    parts.append(int.__repr__(value))
                elif isinstance(value, float):
                    parts.append(_float_repr(value))
                elif not isinstance(value, (list, tuple, dict)):
                    if id(value) in converted or id(value) in open_containers:
                        raise ValueError("Circular reference detected")
                    if default is None:
                        raise TypeError(
                            f"Object of type {type(value).__name__} is not JSON serializable"
                        )
                    converted.add(id(value))
                    value = default(value)
                    continue
                break
            if not isinstance(value, (list, tuple, dict)):
                continue
            if not value:
                parts.append("{}" if isinstance(value, dict) else "[]")
                continue
            if id(value) in open_containers:
                raise ValueError("Circular reference detected")
            open_containers.add(id(value))
            if step is None:
                first, later, close_prefix = "", item_separator, ""
            else:
                newline = "\n" + step * len(stack)
                first, later = newline, item_separator + newline
                close_prefix = "\n" + step * (len(stack) - 1)
            if isinstance(value, dict):
                parts.append("{")
                items = sorted(value.items()) if sort_keys else list(value.items())
                members_of = _prefixed(
                    first, later, ((encode_str(_key_text(k)) + ": ", v) for k, v in items)
                )
                stack.append((members_of, close_prefix + "}", id(value)))
            else:
                parts.append("[")
                members_of = _prefixed(first, later, (("", v) for v in value))
                stack.append((members_of, close_prefix + "]", id(value)))
            break
        else:
            stack.pop()
            parts.append(closer)
            open_containers.discard(marker)
    return "".join(parts)


def _prefixed(
    first: str, later: str, members: Iterator[tuple[str, Any]]
) -> Iterator[tuple[str, Any]]:
    """Each member with the separator that goes before it."""
    for index, (label, value) in enumerate(members):
        yield (later if index else first) + label, value


def _key_text(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is True:
        return "true"
    if key is False:
        return "false"
    if key is None:
        return "null"
    if isinstance(key, int):
        return int.__repr__(key)
    if isinstance(key, float):
        return _float_repr(key)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


def _float_repr(value: float) -> str:
    if value != value:
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    return float.__repr__(value)


def _skip(text: str, index: int) -> int:
    match = _WHITESPACE.match(text, index)
    return match.end() if match else index


def _loads_without_recursion(text: str) -> Any:
    stack: list[tuple[dict[str, Any] | list[Any], str]] = []
    index = _skip(text, 0)
    while True:
        char = text[index : index + 1]
        value: Any
        if char == "{":
            index = _skip(text, index + 1)
            if text[index : index + 1] == "}":
                value, index = {}, index + 1
            else:
                key, index = _object_key(text, index)
                stack.append(({}, key))
                continue
        elif char == "[":
            index = _skip(text, index + 1)
            if text[index : index + 1] == "]":
                value, index = [], index + 1
            else:
                stack.append(([], ""))
                continue
        else:
            value, index = _scalar(text, index)

        while True:
            if not stack:
                index = _skip(text, index)
                if index != len(text):
                    raise JSONDecodeError("Extra data", text, index)
                return value
            container, key = stack[-1]
            if isinstance(container, dict):
                container[key] = value
            else:
                container.append(value)
            index = _skip(text, index)
            char = text[index : index + 1]
            if char == ",":
                index = _skip(text, index + 1)
                if isinstance(container, dict):
                    key, index = _object_key(text, index)
                    stack[-1] = (container, key)
                break
            if char == ("}" if isinstance(container, dict) else "]"):
                value, index = container, index + 1
                stack.pop()
                continue
            raise JSONDecodeError("Expecting ',' delimiter", text, index)


def _object_key(text: str, index: int) -> tuple[str, int]:
    if text[index : index + 1] != '"':
        raise JSONDecodeError("Expecting property name enclosed in double quotes", text, index)
    key, index = _scanstring(text, index + 1, True)
    index = _skip(text, index)
    if text[index : index + 1] != ":":
        raise JSONDecodeError("Expecting ':' delimiter", text, index)
    return key, _skip(text, index + 1)


_CONSTANTS: tuple[tuple[str, Any], ...] = (
    ("null", None),
    ("true", True),
    ("false", False),
    ("NaN", float("nan")),
    ("Infinity", float("inf")),
    ("-Infinity", float("-inf")),
)


def _scalar(text: str, index: int) -> tuple[Any, int]:
    if text[index : index + 1] == '"':
        return _scanstring(text, index + 1, True)
    match = NUMBER_RE.match(text, index)
    if match:
        integer, fraction, exponent = match.groups()
        if fraction or exponent:
            return float(integer + (fraction or "") + (exponent or "")), match.end()
        return int(integer), match.end()
    for word, constant in _CONSTANTS:
        if text.startswith(word, index):
            return constant, index + len(word)
    raise JSONDecodeError("Expecting value", text, index)
