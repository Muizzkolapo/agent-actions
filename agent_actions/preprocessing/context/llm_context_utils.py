"""
LLM Context Computation Utilities.

This module provides utilities for computing what fields will be available
in the next agent's LLM context, based on output schema and context_scope.passthrough.
"""

from typing import Set, Dict, Any


class LLMContextUtils:
    """
    Utility class for computing LLM context from agent configurations.

    The LLM context represents the fields that will be available to the next
    agent's LLM in the workflow pipeline.
    """

    @staticmethod
    def compute_llm_context(agent_config: Dict[str, Any]) -> Set[str]:
        """
        Compute the fields that will be available to the next agent's LLM.

        Formula: schema_fields + passthrough_fields

        The next agent's LLM sees:
        - All fields from the output schema
        - Plus any fields from context_scope.passthrough (passed through from upstream)

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            Set of field names available to the next agent's LLM

        Example:
            >>> config = {
            ...     'output_schema': {'properties': {'summary': {}, 'confidence': {}}},
            ...     'context_scope': {
            ...         'passthrough': ['extractor.document_id', 'source.filename']
            ...     }
            ... }
            >>> LLMContextUtils.compute_llm_context(config)
            {'summary', 'confidence', 'document_id', 'filename'}
        """
        # Get fields from output schema
        schema = agent_config.get("output_schema", {})
        schema_fields = set(schema.get("properties", {}).keys())

        # Get passthrough fields from context_scope
        context_scope = agent_config.get("context_scope", {})
        passthrough_refs = context_scope.get("passthrough", [])

        passthrough_fields = set()
        for field_ref in passthrough_refs:
            # Extract field name from 'action.field' reference
            if isinstance(field_ref, str) and "." in field_ref:
                parts = field_ref.split(".", 1)
                if len(parts) == 2:
                    field_name = parts[1]
                    passthrough_fields.add(field_name)

        # Compute LLM context: schema + passthrough
        llm_context = schema_fields | passthrough_fields

        return llm_context

    @staticmethod
    def compute_output_fields(agent_config: Dict[str, Any]) -> Set[str]:
        """
        Compute the fields that will be in the agent's output.

        Formula: schema_fields + passthrough_fields

        This is the same as LLM context, since the next agent's LLM sees
        everything in the output.

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            Set of field names in the agent's output

        Example:
            >>> config = {
            ...     'output_schema': {'properties': {'summary': {}}},
            ...     'context_scope': {
            ...         'passthrough': ['extractor.document_id']
            ...     }
            ... }
            >>> LLMContextUtils.compute_output_fields(config)
            {'summary', 'document_id'}
        """
        # Output fields are the same as LLM context
        return LLMContextUtils.compute_llm_context(agent_config)
