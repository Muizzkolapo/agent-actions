"""Thread-safe version correlation ID generation for workflow sessions."""

import hashlib
import threading
from collections import OrderedDict


class VersionIdGenerator:
    """Thread-safe version correlation ID generator using a class-level registry."""

    _MAX_REGISTRY_SIZE: int = 10_000
    _version_correlation_registry: OrderedDict[str, str] = OrderedDict()
    _version_correlation_lock = threading.RLock()

    @classmethod
    def get_or_create_version_correlation_id(
        cls, source_guid: str, version_base_name: str, workflow_session_id: str
    ) -> str:
        """Get or create a version correlation ID for a source_guid."""
        registry_key = f"{workflow_session_id}:{version_base_name}:{source_guid}"
        with cls._version_correlation_lock:
            if registry_key in cls._version_correlation_registry:
                cls._version_correlation_registry.move_to_end(registry_key)
                return cls._version_correlation_registry[registry_key]
            content = f"{version_base_name}:{source_guid}"
            correlation_id = cls._generate_deterministic_correlation_id(
                workflow_session_id, content
            )
            cls._version_correlation_registry[registry_key] = correlation_id
            cls._evict_oldest_if_needed()
            return correlation_id

    @classmethod
    def get_or_create_position_based_version_correlation_id(
        cls,
        record_index: int,
        version_base_name: str,
        workflow_session_id: str,
        file_context: str = "",
    ) -> str:
        """Get or create a version correlation ID based on record position."""
        registry_key = (
            f"{workflow_session_id}:{version_base_name}:position_{record_index}:{file_context}"
        )
        with cls._version_correlation_lock:
            if registry_key in cls._version_correlation_registry:
                cls._version_correlation_registry.move_to_end(registry_key)
                return cls._version_correlation_registry[registry_key]
            content = f"{version_base_name}:position_{record_index}:{file_context}"
            correlation_id = cls._generate_deterministic_correlation_id(
                workflow_session_id, content
            )
            cls._version_correlation_registry[registry_key] = correlation_id
            cls._evict_oldest_if_needed()
            return correlation_id

    @classmethod
    def _generate_deterministic_correlation_id(cls, workflow_session_id: str, content: str) -> str:
        """Return a deterministic ``corr_{16_char_hash}`` ID from session and content."""
        hash_input = f"{workflow_session_id}:{content}"
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()
        return f"corr_{hash_digest[:16]}"

    @classmethod
    def _evict_oldest_if_needed(cls) -> None:
        """Evict oldest entries when registry exceeds max size. Must be called under lock."""
        while len(cls._version_correlation_registry) > cls._MAX_REGISTRY_SIZE:
            cls._version_correlation_registry.popitem(last=False)

    @classmethod
    def clear_version_correlation_registry(cls):
        """Clear the version correlation ID registry."""
        with cls._version_correlation_lock:
            cls._version_correlation_registry.clear()

    @classmethod
    def clear(cls) -> None:
        """Short-form alias for clear_version_correlation_registry()."""
        cls.clear_version_correlation_registry()

    @classmethod
    def add_version_correlation_id(
        cls,
        obj: dict,
        agent_config: dict,
        *,
        record_index: int,
    ) -> dict:
        """Add a deterministic position-based ``version_correlation_id`` to *obj*.

        Requires ``version_base_name`` and ``workflow_session_id`` in *agent_config*.
        There is no alternate code path (no source_guid fallback, no optional index).

        Raises:
            ValueError: If required config is missing or ``record_index`` is negative.
        """
        if record_index < 0:
            raise ValueError(
                f"record_index must be non-negative for version correlation IDs, got {record_index}"
            )

        version_base_name = agent_config.get("version_base_name")
        if not version_base_name:
            raise ValueError(
                "version_base_name is required in agent_config for version correlation IDs. "
                "Set it in the action definition (including any tool that emits expansions)."
            )

        workflow_session_id = agent_config.get("workflow_session_id")
        if not workflow_session_id:
            raise ValueError(
                "Missing workflow_session_id in agent_config. "
                "This is required for deterministic correlation IDs. "
                "Ensure AgentWorkflow properly injects session IDs."
            )

        obj = obj.copy()
        obj["version_correlation_id"] = cls.get_or_create_position_based_version_correlation_id(
            record_index, version_base_name, workflow_session_id
        )
        return obj
