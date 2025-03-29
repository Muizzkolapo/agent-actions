
"""
Schema validation utilities.
"""

from pathlib import Path
from agent_actions.handlers.schema_handler import SchemaLoader


class SchemaValidator:
    """Handles schema validation operations."""
    
    @staticmethod
    def validate_schema(agent_name: str, schema_dir: Path) -> None:
        """
        Validate that the required schemas exist.

        Args:
            agent_name: Name of the agent.
            schema_dir: Path to the schema directory.
            
        Raises:
            ValueError: If schema validation fails.
        """
        schema_error = SchemaLoader.validate_schemas_exist(agent_name, str(schema_dir))
        if schema_error:
            raise ValueError(f"Missing schema for {agent_name} in {schema_dir}")