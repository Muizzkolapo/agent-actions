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
        schema_name: str,
        project_root: Path | None = None,
        workflow_name: str | None = None,
    ) -> dict:
        """Load raw schema YAML by name using multi-level resolution.

        Resolution order:

        1. Project-level: ``{project_root}/{schema_path}/{schema_name}.yml``
           (flat match, then rglob in subdirectories)
        2. Current workflow: ``{project_root}/agent_workflow/{workflow_name}/{schema_path}/``
           (only when *workflow_name* is given)
        3. All workflows: ``{project_root}/agent_workflow/*/{schema_path}/``

        ``schema_path`` is read from ``agent_actions.yml`` (required config key).
        Schema names must be globally unique — if the same file name appears in
        more than one location a ``FileNotFoundError`` is raised.
        """
        from agent_actions.config.path_config import get_schema_path

        effective_root = project_root or Path.cwd()
        sp = get_schema_path(effective_root)
        filenames = [f"{schema_name}.yml", f"{schema_name}.yaml"]

        candidates: list[Path] = []
        seen: set[Path] = set()

        def _add_candidate(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(path)

        def _search_dir(search_dir: Path) -> None:
            for fname in filenames:
                flat = search_dir / fname
                if flat.exists():
                    _add_candidate(flat)
                for match in sorted(search_dir.rglob(fname)):
                    _add_candidate(match)

        # Step 1: Project-level schema folder
        project_schema_dir = effective_root / sp
        if project_schema_dir.exists():
            _search_dir(project_schema_dir)

        # Step 2: Current workflow's schema folder
        if workflow_name:
            wf_schema_dir = effective_root / "agent_workflow" / workflow_name / sp
            if wf_schema_dir.exists():
                _search_dir(wf_schema_dir)

        # Step 3: Search ALL workflow schema folders
        wf_root = effective_root / "agent_workflow"
        if wf_root.exists():
            for wf_dir in sorted(wf_root.iterdir()):
                if not wf_dir.is_dir():
                    continue
                wf_sp = wf_dir / sp
                if wf_sp.exists():
                    _search_dir(wf_sp)

        # Enforce global uniqueness
        if len(candidates) > 1:
            match_paths = "\n  ".join(str(c) for c in candidates)
            raise FileNotFoundError(
                f"Schema '{schema_name}.yml' found in multiple locations "
                f"(names must be globally unique):\n  {match_paths}\n"
                f"Move the schema to a single location or use a unique name."
            )

        if not candidates:
            raise FileNotFoundError(
                f"Schema file '{schema_name}.yml' not found. "
                f"Searched project-level ({project_schema_dir}) "
                f"and workflow schema directories under {wf_root if wf_root.exists() else effective_root}."
            )

        schema_file = candidates[0]
        return SchemaLoader._read_schema_file(schema_name, schema_file)

    @staticmethod
    def _read_schema_file(schema_name: str, schema_file: Path) -> dict:
        """Read and parse a schema YAML file, firing observability events."""
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
