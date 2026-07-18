"""Centralized ID generation for processor operations."""

import json
import uuid
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
    def _require_string_keys(obj: Any) -> None:
        """Reject non-string dict keys before hashing.

        A field name becomes a content.source key referenced by name downstream; a numeric
        spreadsheet header or a ragged csv row's None restkey has no usable name and no
        stable identity, so fail loud instead of hashing it ambiguously (stringifying such
        keys would silently collapse distinct keys into one identity).
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                if not isinstance(key, str):
                    raise DataValidationError(
                        f"Record field name {key!r} is a {type(key).__name__}, not a string; "
                        f"first-stage field names must be strings",
                        context={"field": repr(key), "field_type": type(key).__name__},
                    )
                IDGenerator._require_string_keys(value)
        elif isinstance(obj, list):
            for value in obj:
                IDGenerator._require_string_keys(value)

    @staticmethod
    def generate_content_hash(content: Any) -> str:
        """Generate a deterministic UUID5 hash of content (dedup / the basis of derive_source_guid).

        ``default=str`` renders non-JSON-native values (e.g. a spreadsheet date cell) rather
        than raising; it never fires for JSON-native payloads, so existing identities do not
        move. Non-string field names are rejected up front (see ``_require_string_keys``).
        """
        if isinstance(content, dict):
            IDGenerator._require_string_keys(content)
            content_for_hash = json.dumps(content, sort_keys=True, default=str)
        else:
            content_for_hash = str(content)
        return str(uuid.uuid5(uuid.NAMESPACE_OID, content_for_hash))
