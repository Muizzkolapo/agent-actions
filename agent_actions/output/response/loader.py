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

# Collision pairs already warned about, so repeated discovery walks (one per
# action in an inspect run) do not repeat the same warning.
_warned_collisions: set[tuple[str, tuple[str, ...]]] = set()


def _warn_new_collisions(collisions: dict[str, list[Path]]) -> None:
    for name, paths in collisions.items():
        key = (name, tuple(str(p) for p in paths))
        if key in _warned_collisions:
            continue
        _warned_collisions.add(key)
        logger.warning(
            "Schema '%s' found in multiple locations (names must be globally unique): %s",
            name,
            ", ".join(str(p) for p in paths),
        )


class SchemaLoader:
    """Loads, validates, and constructs schemas from YAML/JSON files or inline definitions."""

    @staticmethod
    def _discover(project_root: Path | None) -> tuple[dict[str, Path], dict[str, list[Path]]]:
        """Walk schema dirs once: (stem -> first path, stem -> all colliding paths)."""
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
        result: dict[str, Path] = {}
        collisions: dict[str, list[Path]] = {}
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
                    collisions.setdefault(name, [result[name]]).append(match)
                else:
                    result[name] = match

        return result, collisions

    @staticmethod
    def discover_schema_files(
        project_root: Path | None = None,
    ) -> dict[str, Path]:
        """Discover all schema files, mapping each file stem to its ``Path``.

        Walks ``{project_root}/{schema_path}/`` and every
        ``agent_workflow/*/{schema_path}/`` (``schema_path`` from
        ``agent_actions.yml``). Never fails on a duplicate name — first
        occurrence wins, warned once per process — because the LSP indexer and
        docs scanner call this directly and must not crash on a user project
        state. :meth:`load_schema` is where an ambiguous reference hard-fails.
        """
        result, collisions = SchemaLoader._discover(project_root)
        _warn_new_collisions(collisions)
        return result

    @staticmethod
    def load_schema(
        schema_name: str,
        project_root: Path | None = None,
    ) -> dict:
        """Load raw schema by name using multi-level resolution.

        Supports ``.yml``, ``.yaml``, and ``.json`` schema files.
        Raises ``SchemaValidationError`` when *schema_name* matches more
        than one file — schema names must be globally unique, and picking
        one by directory sort order can validate output against the wrong
        shape.  Raises ``FileNotFoundError`` if the schema is not found.
        """
        from agent_actions.config.path_config import (
            get_required_by_default,
            get_schema_path,
            resolve_project_root,
        )

        effective_root = resolve_project_root(project_root)
        all_schemas, collisions = SchemaLoader._discover(project_root)

        if schema_name in collisions:
            paths = "\n    ".join(str(p) for p in collisions[schema_name])
            raise SchemaValidationError(
                f"Schema '{schema_name}' is ambiguous — found in "
                f"{len(collisions[schema_name])} locations "
                f"(names must be globally unique):\n    {paths}",
                validation_type="uniqueness",
                hint="Rename the colliding files so every schema name is unique.",
            )
        _warn_new_collisions(collisions)

        if schema_name not in all_schemas:
            sp = get_schema_path(effective_root)
            project_schema_dir = resolve_relative_to(sp, effective_root)
            wf_root = effective_root / "agent_workflow"
            raise FileNotFoundError(
                f"Schema file '{schema_name}' not found. "
                f"Searched project-level ({project_schema_dir}) "
                f"and workflow schema directories under "
                f"{wf_root if wf_root.exists() else effective_root}."
            )

        schema_data = SchemaLoader._read_schema_file(schema_name, all_schemas[schema_name])
        # A schema that does not declare its own policy inherits the project-wide
        # required_by_default from agent_actions.yml. Per-schema declaration wins.
        if isinstance(schema_data, dict) and "required_by_default" not in schema_data:
            schema_data["required_by_default"] = get_required_by_default(effective_root)
        return schema_data

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
            if not isinstance(field_type, str):
                raise SchemaValidationError(
                    f"Inline schema field '{field_name}' has a non-string type "
                    f"({type(field_type).__name__}). Inline shorthand only supports "
                    f"string type descriptors (e.g., 'string', 'integer', 'array[string]').",
                    validation_type="structure",
                    hint="Use a schema file for complex nested definitions.",
                )
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
                if not isinstance(prop_type, str):
                    raise SchemaValidationError(
                        f"Object property '{prop_name}' has a non-string type "
                        f"({type(prop_type).__name__}). Property types must be "
                        f"string descriptors (e.g., 'string', 'number!').",
                        validation_type="structure",
                        hint="Use a schema file for complex nested definitions.",
                    )
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
