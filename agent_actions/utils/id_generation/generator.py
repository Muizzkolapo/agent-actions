"""Centralized ID generation for processor operations."""

import json
import uuid
from typing import Any


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
    def generate_content_hash(content: Any) -> str:
        """Generate a deterministic UUID5 hash of content (dedup / the basis of derive_source_guid)."""
        if isinstance(content, dict):
            content_for_hash = json.dumps(content, sort_keys=True)
        else:
            content_for_hash = str(content)
        return str(uuid.uuid5(uuid.NAMESPACE_OID, content_for_hash))
