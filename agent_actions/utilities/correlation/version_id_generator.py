"""
Version Correlation Service.
"""

import threading
import hashlib
from typing import Dict, Optional


class VersionIdGenerator:
    """
    Thread-safe version correlation ID generator.

    Uses a class-level registry to maintain correlation IDs across
    all processor instances within a workflow session.
    """

    _version_correlation_registry: Dict[str, str] = {}
    _version_correlation_lock = threading.RLock()

    @classmethod
    def get_or_create_version_correlation_id(
        cls, source_guid: str, version_base_name: str, workflow_session_id: str
    ) -> str:
        """
        Get or create a version correlation ID for a source_guid.

        Args:
            source_guid: Source GUID of the record
            version_base_name: Base name of the version
                           (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for
                                deterministic correlation

        Returns:
            Consistent version correlation ID for this combination
        """
        registry_key = f"{workflow_session_id}:{version_base_name}:{source_guid}"
        with cls._version_correlation_lock:
            if registry_key not in cls._version_correlation_registry:
                content = f"{version_base_name}:{source_guid}"
                correlation_id = cls._generate_deterministic_correlation_id(
                    workflow_session_id, content
                )
                cls._version_correlation_registry[registry_key] = correlation_id
            return cls._version_correlation_registry[registry_key]

    @classmethod
    def get_or_create_position_based_version_correlation_id(
        cls,
        record_index: int,
        version_base_name: str,
        workflow_session_id: str,
        file_context: str = "",
    ) -> str:
        """
        Get or create a version correlation ID based on record position.

        Args:
            record_index: Position/index of the record in the input list
            version_base_name: Base name of the version
                           (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for
                                deterministic correlation
            file_context: Optional file context for uniqueness

        Returns:
            Consistent version correlation ID for this position across
            all version iterations
        """
        registry_key = (
            f"{workflow_session_id}:{version_base_name}:position_{record_index}:{file_context}"
        )
        with cls._version_correlation_lock:
            if registry_key not in cls._version_correlation_registry:
                content = f"{version_base_name}:position_{record_index}:{file_context}"
                correlation_id = cls._generate_deterministic_correlation_id(
                    workflow_session_id, content
                )
                cls._version_correlation_registry[registry_key] = correlation_id
            return cls._version_correlation_registry[registry_key]

    @classmethod
    def _generate_deterministic_correlation_id(cls, workflow_session_id: str, content: str) -> str:
        """
        Generate a deterministic correlation ID based on session.

        Args:
            workflow_session_id: The workflow session identifier
            content: The content to hash (version_base_name:source_guid
                    or position info)

        Returns:
            Deterministic correlation ID in format: corr_{16_char_hash}
        """
        hash_input = f"{workflow_session_id}:{content}"
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()
        return f"corr_{hash_digest[:16]}"

    @classmethod
    def clear_version_correlation_registry(cls):
        """
        Clear the version correlation ID registry.

        Useful for testing or workflow resets.
        """
        with cls._version_correlation_lock:
            cls._version_correlation_registry.clear()

    @classmethod
    def add_version_correlation_id(
        cls, obj: Dict, agent_config: Dict, record_index: Optional[int] = None
    ) -> Dict:
        """
        Add version correlation ID to an object if agent is versioned.

        Args:
            obj: Object to potentially add version correlation ID to
            agent_config: Agent configuration to check for version metadata
            record_index: Optional position/index of the record

        Returns:
            Object with version correlation ID added if applicable

        Raises:
            ValueError: If workflow_session_id is missing in version context
        """
        if not agent_config.get("is_versioned_agent", False):
            return obj

        version_base_name = agent_config.get("version_base_name")
        if not version_base_name:
            return obj

        workflow_session_id = agent_config.get("workflow_session_id")
        if not workflow_session_id:
            raise ValueError(
                "Missing workflow_session_id in agent_config. "
                "This is required for deterministic correlation IDs. "
                "Ensure AgentWorkflow properly injects session IDs."
            )

        obj = obj.copy()
        if record_index is not None:
            obj["version_correlation_id"] = cls.get_or_create_position_based_version_correlation_id(
                record_index, version_base_name, workflow_session_id
            )
        else:
            source_guid = obj.get("source_guid")
            if source_guid:
                obj["version_correlation_id"] = cls.get_or_create_version_correlation_id(
                    source_guid, version_base_name, workflow_session_id
                )
        return obj
