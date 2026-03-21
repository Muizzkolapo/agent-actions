"""Schema loading utilities for batch and online modes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml

from agent_actions.errors import (
    SchemaValidationError,
)
from agent_actions.logging import LoggerFactory, fire_event
from agent_actions.logging.events import (
    SchemaConstructionCompleteEvent,
    SchemaConstructionStartedEvent,
    SchemaLoadedEvent,
    SchemaLoadingStartedEvent,
)

logger = LoggerFactory.get_logger(__name__)


class SchemaLoader:
    """Loads, validates, and constructs schemas from YAML files or inline definitions."""

    @staticmethod
    def load_schema(
        schema_name: str, schema_dir: Path | None = None, project_root: Path | None = None
    ) -> dict:
        """Load raw schema YAML by name, searching schema_dir (default: project_root/schema)."""
        if schema_dir is None:
            schema_dir = (project_root or Path.cwd()) / "schema"

        schema_file = schema_dir / f"{schema_name}.yml"

        if not schema_file.exists() and schema_dir.exists():
            # Try recursive search in subdirectories
            matches = sorted(schema_dir.rglob(f"{schema_name}.yml"))
            if len(matches) == 1:
                schema_file = matches[0]
                logger.info(
                    "Schema '%s' found at %s (not in root schema dir)",
                    schema_name,
                    schema_file,
                )
            elif len(matches) > 1:
                match_paths = "\n  ".join(str(m.relative_to(schema_dir)) for m in matches)
                raise FileNotFoundError(
                    f"Multiple schema files named '{schema_name}.yml' found in {schema_dir}:\n  {match_paths}\n"
                    f"Move the schema to schema/{schema_name}.yml or use a unique name."
                )

        if not schema_file.exists():
            raise FileNotFoundError(
                f"Schema file '{schema_name}.yml' not found in {schema_dir} "
                f"or any subdirectory. Ensure the schema file exists in the schema/ directory."
            )

        fire_event(
            SchemaLoadingStartedEvent(
                schema_name=schema_name,
                schema_path=str(schema_file),
            )
        )

        with open(schema_file, encoding="utf-8") as f:
            schema_data = yaml.safe_load(f)

        field_count = len(schema_data.get("fields", [])) if isinstance(schema_data, dict) else 0

        fire_event(
            SchemaLoadedEvent(
                schema_name=schema_name,
                field_count=field_count,
            )
        )

        return schema_data  # type: ignore[no-any-return]

    @staticmethod
    def construct_schema_from_dict(schema_dict: dict) -> dict:
        """Construct a unified schema from a {field_name: type_string} dictionary."""
        fire_event(
            SchemaConstructionStartedEvent(
                schema_type="dict",
            )
        )

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

        # Fire event after schema construction
        fire_event(
            SchemaConstructionCompleteEvent(
                schema_type="dict",
                field_count=len(fields),
            )
        )

        return unified_schema

    @staticmethod
    def _parse_object_properties(properties_str: str) -> dict:
        """Parse object properties from string notation (e.g., "{'prop': 'type'}")."""
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
            logger.error(
                "Failed to parse object properties '%s': %s",
                properties_str,
                str(e),
            )
            raise SchemaValidationError(
                f"Invalid object properties format: '{properties_str}'",
                validation_type="structure",
                hint=(
                    "Object properties must be valid Python dict or JSON format, "
                    "e.g., \"{'name': 'string', 'age': 'number'}\""
                ),
                cause=e,
            ) from e
