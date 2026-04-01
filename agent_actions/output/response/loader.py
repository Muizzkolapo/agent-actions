"""Schema loading utilities for batch and online modes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from agent_actions.errors import (
    SchemaValidationError,
)
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    SchemaConstructionCompleteEvent,
    SchemaConstructionStartedEvent,
    SchemaLoadedEvent,
    SchemaLoadingStartedEvent,
)
from agent_actions.logging.factory import LoggerFactory
from agent_actions.utils.constants import SCHEMA_SUFFIXES
from agent_actions.utils.file_utils import load_structured_file
from agent_actions.utils.path_utils import resolve_relative_to

logger = LoggerFactory.get_logger(__name__)


class SchemaLoader:
    """Loads, validates, and constructs schemas from YAML/JSON files or inline definitions."""

    @staticmethod
    def discover_schema_files(
        project_root: Path | None = None,
    ) -> dict[str, Path]:
        """Discover all schema files across project and workflow directories.

        Searches recursively through:

        1. Project-level: ``{project_root}/{schema_path}/``
        2. All workflows: ``{project_root}/agent_workflow/*/{schema_path}/``

        ``schema_path`` is read from ``agent_actions.yml`` (required config key).

        Returns a dict mapping ``schema_name`` (file stem) to its ``Path``.
        When a schema name appears in multiple locations the first occurrence
        wins and a warning is logged.  Callers that need strict uniqueness
        (e.g. :meth:`load_schema`) enforce it themselves.
        """
        from agent_actions.config.path_config import get_schema_path, resolve_project_root

        effective_root = resolve_project_root(project_root)
        sp = get_schema_path(effective_root)

        # Collect search directories
        search_dirs: list[Path] = []
        project_schema_dir = resolve_relative_to(sp, effective_root)
        if project_schema_dir.exists():
            search_dirs.append(project_schema_dir)
        wf_root = effective_root / "agent_workflow"
        if wf_root.exists():
            for wf_dir in sorted(wf_root.iterdir()):
                if wf_dir.is_dir():
                    wf_sp = wf_dir / sp
                    if wf_sp.exists():
                        search_dirs.append(wf_sp)

        # Discover all schema files, deduplicating by resolved path.
        # First occurrence wins; duplicates are logged but not fatal.
        result: dict[str, Path] = {}
        seen: set[Path] = set()

        for search_dir in search_dirs:
            for match in sorted(search_dir.rglob("*")):
                if match.suffix not in SCHEMA_SUFFIXES:
                    continue
                resolved = match.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                name = match.stem
                if name in result:
                    logger.warning(
                        "Schema '%s' found in multiple locations "
                        "(names must be globally unique): %s and %s",
                        name,
                        result[name],
                        match,
                    )
                else:
                    result[name] = match

        return result

    @staticmethod
    def load_schema(
        schema_name: str,
        project_root: Path | None = None,
    ) -> dict:
        """Load raw schema by name using multi-level resolution.

        Supports ``.yml``, ``.yaml``, and ``.json`` schema files.
        Delegates to :meth:`discover_schema_files` and looks up the
        requested *schema_name*.  Raises ``FileNotFoundError`` if the
        schema is not found.  Duplicate names are logged as warnings
        by ``discover_schema_files``; the first occurrence is used.
        """
        from agent_actions.config.path_config import get_schema_path, resolve_project_root

        all_schemas = SchemaLoader.discover_schema_files(project_root)

        if schema_name not in all_schemas:
            effective_root = resolve_project_root(project_root)
            sp = get_schema_path(effective_root)
            project_schema_dir = resolve_relative_to(sp, effective_root)
            wf_root = effective_root / "agent_workflow"
            raise FileNotFoundError(
                f"Schema file '{schema_name}' not found. "
                f"Searched project-level ({project_schema_dir}) "
                f"and workflow schema directories under "
                f"{wf_root if wf_root.exists() else effective_root}."
            )

        return SchemaLoader._read_schema_file(schema_name, all_schemas[schema_name])

    @staticmethod
    def _read_schema_file(schema_name: str, schema_file: Path) -> dict:
        """Read and parse a schema file (YAML or JSON), firing observability events."""
        fire_event(
            SchemaLoadingStartedEvent(
                schema_name=schema_name,
                schema_path=str(schema_file),
            )
        )

        schema_data = load_structured_file(schema_file)

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
