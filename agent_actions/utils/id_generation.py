"""Centralized ID generation for processor operations."""

import json
import uuid
from collections.abc import Iterator
from json.encoder import encode_basestring_ascii
from typing import Any

from agent_actions.errors import DataValidationError


class IDGenerator:
    """Centralized ID generation service for processor operations."""

    @staticmethod
    def generate_target_id() -> str:
        """Generate a unique UUID4 target ID."""
        return str(uuid.uuid4())

    @staticmethod
    def generate_node_id(action_name: str) -> str:
        """Generate a node ID in the format ``{action_name}_{uuid}``."""
        return f"{action_name}_{uuid.uuid4()}"

    @staticmethod
    def generate_source_guid() -> str:
        """Generate a random UUID4 identity for a genuinely new entity (expansion child, synthetic)."""
        return str(uuid.uuid4())

    @staticmethod
    def derive_source_guid(record: Any) -> str:
        """Deterministic UUID5 identity over a first-stage record's raw content.

        Hashes the payload as given — nothing is stripped by name. Callers MUST derive
        BEFORE the volatile envelope (target_id/batch_id/node_id) is added, so identity is
        stable across runs and a user field sharing a framework name stays part of identity
        (no silent collision). A bare string normalizes to ``{"content": str}``.
        """
        if isinstance(record, str):
            content: Any = {"content": record}
        else:
            content = record
        return IDGenerator.generate_content_hash(content)

    @staticmethod
    def derive_repeat_source_guid(base_source_guid: str, occurrence: int) -> str:
        """Deterministic identity for the *occurrence*-th repeat of one content.

        Identity is derived from content, so a record staged twice lands on one
        guid — and the store is keyed on it, so the second would be dropped. A
        repeat is a record the user staged; it gets an identity of its own here,
        derived from the one it repeats so it is stable across runs, and records
        that one as ``repeat_of_source_guid`` — not ``parent_source_guid``, which
        means the record's own guid matches nothing in the source pool. A repeat's
        does.

        Hashed in a different UUID namespace from record content, so no payload
        can produce one of these however it is shaped. Deriving it in the content
        namespace over ``{"repeat_of": ..., "occurrence": ...}`` would be reachable
        by a record whose fields happen to be exactly that.
        """
        if occurrence < 1:
            raise ValueError(f"occurrence must be at least 1, got {occurrence}")
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"agac:repeat:{base_source_guid}:{occurrence}"))

    @staticmethod
    def _require_string_keys(obj: Any) -> None:
        """Reject non-string dict keys before hashing.

        A field name becomes a content.source key referenced by name downstream; a numeric
        spreadsheet header or a ragged csv row's None restkey has no usable name and no
        stable identity, so fail loud instead of hashing it ambiguously (stringifying such
        keys would silently collapse distinct keys into one identity).

        Walked on a stack of iterators, not by recursion: a record about 800 levels deep
        would otherwise fail here before it is hashed.
        """
        seen: set[int] = set()
        stack: list[Iterator[Any]] = [iter((obj,))]
        while stack:
            for node in stack[-1]:
                if isinstance(node, (dict, list)):
                    if id(node) in seen:
                        continue
                    seen.add(id(node))
                    stack.append(
                        IDGenerator._string_keyed_values(node)
                        if isinstance(node, dict)
                        else iter(node)
                    )
                    break
            else:
                stack.pop()

    @staticmethod
    def _string_keyed_values(node: dict) -> Iterator[Any]:
        """The values of *node*, each yielded once its key has been checked."""
        for key, value in node.items():
            if not isinstance(key, str):
                raise DataValidationError(
                    f"Record field name {key!r} is a {type(key).__name__}, not a string; "
                    f"first-stage field names must be strings",
                    context={"field": repr(key), "field_type": type(key).__name__},
                )
            yield value

    @staticmethod
    def generate_content_hash(content: Any) -> str:
        """Generate a deterministic UUID5 hash of content (dedup / the basis of derive_source_guid).

        ``default=str`` renders non-JSON-native values (e.g. a spreadsheet date cell) rather
        than raising; it never fires for JSON-native payloads, so existing identities do not
        move. Non-string field names are rejected up front (see ``_require_string_keys``).
        """
        if isinstance(content, dict):
            IDGenerator._require_string_keys(content)
            try:
                content_for_hash = json.dumps(content, sort_keys=True, default=str)
            except RecursionError:
                content_for_hash = _dumps_without_recursion(content)
        else:
            content_for_hash = str(content)
        return str(uuid.uuid5(uuid.NAMESPACE_OID, content_for_hash))


def _dumps_without_recursion(obj: Any) -> str:
    """The bytes of ``json.dumps(obj, sort_keys=True, default=str)``, built on a stack.

    Python 3.11's encoder recurses once per nesting level and gives up about 1000 levels
    down; identity is a hash of these bytes, so this must match the encoder exactly.
    """
    parts: list[str] = []
    open_containers: set[int] = set()
    stack: list[tuple[Iterator[tuple[str, Any]], str, int]] = [(iter((("", obj),)), "", -1)]
    while stack:
        members, closer, marker = stack[-1]
        for prefix, value in members:
            parts.append(prefix)
            if value is None:
                parts.append("null")
            elif value is True:
                parts.append("true")
            elif value is False:
                parts.append("false")
            elif isinstance(value, str):
                parts.append(encode_basestring_ascii(value))
            elif isinstance(value, int):
                parts.append(int.__repr__(value))
            elif isinstance(value, float):
                parts.append(_float_repr(value))
            elif isinstance(value, (list, tuple, dict)):
                if not value:
                    parts.append("{}" if isinstance(value, dict) else "[]")
                    continue
                if id(value) in open_containers:
                    raise ValueError("Circular reference detected")
                open_containers.add(id(value))
                if isinstance(value, dict):
                    parts.append("{")
                    children: Iterator[tuple[str, Any]] = (
                        (("" if i == 0 else ", ") + encode_basestring_ascii(k) + ": ", v)
                        for i, (k, v) in enumerate(sorted(value.items()))
                    )
                    stack.append((children, "}", id(value)))
                else:
                    parts.append("[")
                    children = (("" if i == 0 else ", ", v) for i, v in enumerate(value))
                    stack.append((children, "]", id(value)))
                break
            else:
                parts.append(encode_basestring_ascii(str(value)))
        else:
            stack.pop()
            parts.append(closer)
            open_containers.discard(marker)
    return "".join(parts)


def _float_repr(value: float) -> str:
    if value != value:
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    return float.__repr__(value)
