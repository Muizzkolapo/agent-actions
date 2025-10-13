"""
LLM Context Computation Utilities.

This module provides utilities for computing what fields will be available
in the next agent's LLM context, based on output schema, observe, and drops directives.
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

        Formula: (schema_fields + observe) - drops

        The next agent's LLM sees:
        - All fields from the output schema
        - Plus any fields from 'observe' (pass-through from input)
        - Minus any fields in 'drops' (removed from output)

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            Set of field names available to the next agent's LLM

        Example:
            >>> config = {
            ...     'output_schema': {'properties': {'summary': {}, 'temp': {}}},
            ...     'observe': ['document_id'],
            ...     'drops': ['temp']
            ... }
            >>> LLMContextUtils.compute_llm_context(config)
            {'summary', 'document_id'}
        """
        # Get fields from output schema
        schema = agent_config.get('output_schema', {})
        schema_fields = set(schema.get('properties', {}).keys())

        # Get pass-through fields from input (observe or observe)
        # Note: 'observe' is the YAML field name, 'observe' is the internal Pydantic field name
        observe = set(agent_config.get('observe', agent_config.get('observe', [])))

        # Get fields to remove from output (drops or drops)
        # Note: 'drops' is the YAML field name, 'drops' is the internal Pydantic field name
        drops = set(agent_config.get('drops', agent_config.get('drops', [])))

        # Compute LLM context: (schema + observe) - drops
        llm_context = (schema_fields | observe) - drops

        return llm_context

    @staticmethod
    def compute_output_fields(agent_config: Dict[str, Any]) -> Set[str]:
        """
        Compute the fields that will be in the agent's output.

        Formula: (schema_fields + observe) - drops

        This is the same as LLM context (without input_data), since the next
        agent's LLM sees everything in the output.

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            Set of field names in the agent's output

        Example:
            >>> config = {
            ...     'output_schema': {'properties': {'summary': {}}},
            ...     'observe': ['original_id'],
            ...     'drops': []
            ... }
            >>> LLMContextUtils.compute_output_fields(config)
            {'summary', 'original_id'}
        """
        # Get fields from output schema
        schema = agent_config.get('output_schema', {})
        schema_fields = set(schema.get('properties', {}).keys())

        # Get pass-through fields from input (observe or observe)
        # Note: 'observe' is the YAML field name, 'observe' is the internal Pydantic field name
        observe = set(agent_config.get('observe', agent_config.get('observe', [])))

        # Get fields to remove from output (drops or drops)
        # Note: 'drops' is the YAML field name, 'drops' is the internal Pydantic field name
        drops = set(agent_config.get('drops', agent_config.get('drops', [])))

        # Output fields: (schema + observe) - drops
        output_fields = (schema_fields | observe) - drops

        return output_fields
