# pylint: disable=cyclic-import
"""
Schema loading utilities.

This module provides schema loading functionality used by both batch and realtime modes.
Moved from llm_invocation/realtime/ to response_processing/ to reflect its shared usage.
"""

import ast
import json
from pathlib import Path

import yaml

from agent_actions.io.file_handler import FileHandler
from agent_actions.prompt_generation.render_workflow import render_pipeline_with_templates


class SchemaLoader:
    """
    A class for loading schemas.
    """

    @staticmethod
    def return_schema(agent_name: str) -> set:
        """
        Return the set of schema names used by an agent.

        Args:
            agent_name (str): The name of the agent

        Returns:
            set: Set of schema names, or empty set if an error occurs
        """
        try:
            agent_config_dir, _, _ = FileHandler.get_agent_paths(agent_name)
            agent_config_file = FileHandler.find_config_file(agent_config_dir, f"{agent_name}.yml")
            current_dir = Path.cwd()
            template_dir = current_dir / "templates"
            rendered_templates = render_pipeline_with_templates(
                agent_config_file, str(template_dir)
            )
            data = yaml.safe_load(rendered_templates)
            dynamic_schema_names = {
                step["schema_name"]
                for key, steps in data.items()
                if isinstance(steps, list)
                for step in steps
                if "schema_name" in step
            }
            return dynamic_schema_names
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"Error rendering schema for agent '{agent_name}': {str(e)}")
            return set()  # Return empty set on error

    @staticmethod
    def load_schema(schema_name: str, schema_dir: Path = None) -> dict:
        """
        Load a schema using WorkflowParser.

        Parameters:
            schema_name (str): The name of the schema to load.
            schema_dir (Path): Optional schema directory. Defaults to cwd/schema.

        Returns:
            dict: The loaded schema as a dictionary.
        """
        # Import here to avoid circular imports
        from agent_actions.docs.parser import (  # pylint: disable=import-outside-toplevel
            WorkflowParser,
        )

        if schema_dir is None:
            schema_dir = Path.cwd() / "schema"

        result = WorkflowParser.load_schema(schema_name, schema_dir)
        if result:
            return result

        raise FileNotFoundError(
            f"Schema file '{schema_name}.yml' not found in {schema_dir}. "
            f"Ensure the schema file exists in the schema/ directory."
        )

    @staticmethod
    def validate_schemas_exist(
        agent_name: str,
        directory: str = None,  # pylint: disable=unused-argument
    ) -> None:
        """
        Validates that each schema file exists anywhere in the project.

        Args:
            agent_name (str): The name of the agent.
            directory (str): Deprecated parameter, kept for backward compatibility.

        Raises:
            SingleSchemaMissingError: If one schema file is missing.
            MultipleSchemaMissingError: If multiple schema files are missing.
        """
        schema_names = SchemaLoader.return_schema(agent_name)
        missing_files = []
        for schema_name in schema_names:
            try:
                if not SchemaLoader.load_schema(schema_name):
                    missing_files.append(f"{schema_name}.yml")
            except FileNotFoundError:
                missing_files.append(f"{schema_name}.yml")
        if missing_files:
            if len(missing_files) == 1:
                print(f"Schema file missing: {missing_files[0]}")
            else:
                print(f"Multiple schema files missing: {', '.join(missing_files)}")

    @staticmethod
    def construct_schema_from_dict(schema_dict: dict) -> dict:
        """
        Construct a unified schema from a simple key-value dictionary.

        Args:
            schema_dict (dict): Simple dictionary where keys are field names
                               and values are data types (e.g., {"name": "string", "age": "number"})

        Returns:
            dict: A unified schema in the standard format
        """
        fields = []
        for field_name, field_type in schema_dict.items():
            is_required = field_type.endswith("!")
            if is_required:
                field_type = field_type[:-1]
            if field_type.startswith("array[") and field_type.endswith("]"):
                item_type = field_type[6:-1]
                if item_type.startswith("object:"):
                    properties_str = item_type[7:]
                    items_def = SchemaLoader._parse_object_properties(properties_str)
                    field_def = {
                        "id": field_name,
                        "type": "array",
                        "items": items_def,
                        "required": is_required,
                    }
                else:
                    field_def = {
                        "id": field_name,
                        "type": "array",
                        "items": {"type": item_type},
                        "required": is_required,
                    }
            elif field_type == "array":
                field_def = {
                    "id": field_name,
                    "type": "array",
                    "items": {"type": "string"},
                    "required": is_required,
                }
            else:
                field_def = {"id": field_name, "type": field_type, "required": is_required}
            fields.append(field_def)
        unified_schema = {"name": "InlineSchema", "fields": fields}
        return unified_schema

    @staticmethod
    def _parse_object_properties(properties_str: str) -> dict:
        """
        Parse object properties from string notation like "{'prop': 'type'}"

        Args:
            properties_str (str): String representation of object properties

        Returns:
            dict: Object schema with type and properties
        """
        try:
            properties_str = properties_str.strip()
            try:
                properties_dict = ast.literal_eval(properties_str)
            except (ValueError, SyntaxError):
                properties_dict = json.loads(properties_str)
            schema_properties = {}
            required_fields = []
            for prop_name, prop_type in properties_dict.items():
                is_required = prop_type.endswith("!")
                if is_required:
                    prop_type = prop_type[:-1]
                    required_fields.append(prop_name)
                schema_properties[prop_name] = {"type": prop_type}
            object_schema = {"type": "object", "properties": schema_properties}
            if required_fields:
                object_schema["required"] = required_fields
            return object_schema
        except (ValueError, SyntaxError, json.JSONDecodeError) as e:
            print(f"Warning: Could not parse object properties '{properties_str}': {e}")
            return {"type": "object"}
