"""
ID Generation Service.
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
    def generate_node_id(action_name: str) -> str:
        """
        Generate a unique node ID for an action.

        Args:
            action_name: Name of the action

        Returns:
            A node ID in the format "{action_name}_{uuid}"
        """
        return f"{action_name}_{uuid.uuid4()}"

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
