"""Centralized ID generation for processor operations."""

import json
import uuid
from typing import Any

from agent_actions.record.envelope import SOURCE_GUID_EXCLUDED_FIELDS


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
        """Deterministic source_guid for a first-stage record: UUID5 over its content.

        The same input content always yields the same guid (across runs and stamp
        sites), so the disposition/checkpoint gate matches records on re-run and the
        ingestion and processing stamps agree. The volatile envelope/identity fields in
        ``SOURCE_GUID_EXCLUDED_FIELDS`` are excluded from the hash.

        Note: the exclusion is name-based — a user content field named exactly like an
        excluded field (e.g. `node_id`, `batch_id`) is dropped from the hash. Those
        names are reserved.
        """
        if isinstance(record, dict):
            content: Any = {k: v for k, v in record.items() if k not in SOURCE_GUID_EXCLUDED_FIELDS}
        elif isinstance(record, str):
            # A first-stage text chunk is stamped from a {"content": text} wrapper at
            # some sites and from the raw string at others; normalize so they agree.
            content = {"content": record}
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
