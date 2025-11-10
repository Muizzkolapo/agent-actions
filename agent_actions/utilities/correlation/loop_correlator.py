"""
Loop Correlation Service.

This module provides thread-safe loop correlation ID management:
- Generate deterministic correlation IDs for loop contexts
- Maintain a registry for consistency across loop iterations
- Support both source_guid-based and position-based correlation
"""
import threading
import hashlib
from typing import Dict, Optional


class LoopCorrelator:
    """
    Thread-safe loop correlation ID manager.

    Uses a class-level registry to maintain correlation IDs across
    all processor instances within a workflow session.
    """

    _loop_correlation_registry: Dict[str, str] = {}
    _loop_correlation_lock = threading.RLock()

    @classmethod
    def get_or_create_loop_correlation_id(
        cls,
        source_guid: str,
        loop_base_name: str,
        workflow_session_id: str
    ) -> str:
        """
        Get or create a loop correlation ID for a source_guid.

        Args:
            source_guid: Source GUID of the record
            loop_base_name: Base name of the loop
                           (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for
                                deterministic correlation

        Returns:
            Consistent loop correlation ID for this combination
        """
        registry_key = (
            f'{workflow_session_id}:{loop_base_name}:{source_guid}'
        )
        with cls._loop_correlation_lock:
            if registry_key not in cls._loop_correlation_registry:
                content = f'{loop_base_name}:{source_guid}'
                correlation_id = cls._generate_deterministic_correlation_id(
                    workflow_session_id,
                    content
                )
                cls._loop_correlation_registry[registry_key] = correlation_id
            return cls._loop_correlation_registry[registry_key]

    @classmethod
    def get_or_create_position_based_loop_correlation_id(
        cls,
        record_index: int,
        loop_base_name: str,
        workflow_session_id: str,
        file_context: str = ''
    ) -> str:
        """
        Get or create a loop correlation ID based on record position.

        Args:
            record_index: Position/index of the record in the input list
            loop_base_name: Base name of the loop
                           (e.g., 'generate_distractors')
            workflow_session_id: Workflow session identifier for
                                deterministic correlation
            file_context: Optional file context for uniqueness

        Returns:
            Consistent loop correlation ID for this position across
            all loop iterations
        """
        registry_key = (
            f'{workflow_session_id}:{loop_base_name}:'
            f'position_{record_index}:{file_context}'
        )
        with cls._loop_correlation_lock:
            if registry_key not in cls._loop_correlation_registry:
                content = (
                    f'{loop_base_name}:position_{record_index}:'
                    f'{file_context}'
                )
                correlation_id = cls._generate_deterministic_correlation_id(
                    workflow_session_id,
                    content
                )
                cls._loop_correlation_registry[registry_key] = correlation_id
            return cls._loop_correlation_registry[registry_key]

    @classmethod
    def _generate_deterministic_correlation_id(
        cls,
        workflow_session_id: str,
        content: str
    ) -> str:
        """
        Generate a deterministic correlation ID based on session.

        Args:
            workflow_session_id: The workflow session identifier
            content: The content to hash (loop_base_name:source_guid
                    or position info)

        Returns:
            Deterministic correlation ID in format: corr_{16_char_hash}
        """
        hash_input = f'{workflow_session_id}:{content}'
        hash_digest = hashlib.sha256(hash_input.encode()).hexdigest()
        return f'corr_{hash_digest[:16]}'

    @classmethod
    def clear_loop_correlation_registry(cls):
        """
        Clear the loop correlation ID registry.

        Useful for testing or workflow resets.
        """
        with cls._loop_correlation_lock:
            cls._loop_correlation_registry.clear()

    @classmethod
    def add_loop_correlation_id(
        cls,
        obj: Dict,
        agent_config: Dict,
        record_index: Optional[int] = None
    ) -> Dict:
        """
        Add loop correlation ID to an object if agent is in a loop.

        Args:
            obj: Object to potentially add loop correlation ID to
            agent_config: Agent configuration to check for loop metadata
            record_index: Optional position/index of the record

        Returns:
            Object with loop correlation ID added if applicable

        Raises:
            ValueError: If workflow_session_id is missing in loop context
        """
        if not agent_config.get('is_loop_agent', False):
            return obj

        loop_base_name = agent_config.get('loop_base_name')
        if not loop_base_name:
            return obj

        workflow_session_id = agent_config.get('workflow_session_id')
        if not workflow_session_id:
            raise ValueError(
                'Missing workflow_session_id in agent_config. '
                'This is required for deterministic correlation IDs. '
                'Ensure AgentWorkflow properly injects session IDs.'
            )

        obj = obj.copy()
        if record_index is not None:
            obj['loop_correlation_id'] = (
                cls.get_or_create_position_based_loop_correlation_id(
                    record_index,
                    loop_base_name,
                    workflow_session_id
                )
            )
        else:
            source_guid = obj.get('source_guid')
            if source_guid:
                obj['loop_correlation_id'] = (
                    cls.get_or_create_loop_correlation_id(
                        source_guid,
                        loop_base_name,
                        workflow_session_id
                    )
                )
        return obj
