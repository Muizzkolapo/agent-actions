"""
ID Generation Service.

This module provides centralized ID generation utilities for processors:
- UUID4 target IDs
- Node IDs with index prefix
- Deterministic UUID5 GUIDs from content
"""

import uuid
import json
from typing import Any


class IDGenerator:
    """Centralized ID generation service for processor operations."""

    @staticmethod
    def generate_target_id() -> str:
        """
        Generate a unique target ID.

        Returns:
            A UUID4 string for use as target_id
        """
        return str(uuid.uuid4())

    @staticmethod
    def generate_node_id(idx: int) -> str:
        """
        Generate a unique node ID with index prefix.

        Args:
            idx: Index to include in the node ID

        Returns:
            A node ID in the format "node_{idx}_{uuid}"
        """
        return f"node_{idx}_{uuid.uuid4()}"

    @staticmethod
    def generate_deterministic_source_guid(content: Any) -> str:
        """
        Generate a deterministic source GUID based on content.

        Args:
            content: Content to generate GUID from

        Returns:
            A deterministic UUID5 string
        """
        if isinstance(content, dict):
            content_for_hash = json.dumps(content, sort_keys=True)
        else:
            content_for_hash = str(content)
        return str(uuid.uuid5(uuid.NAMESPACE_OID, content_for_hash))
