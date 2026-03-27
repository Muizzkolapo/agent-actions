"""Schema file validation with JSON Schema meta-schema checks."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import yaml

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    DataValidationFailedEvent,
    DataValidationPassedEvent,
)
from agent_actions.utils.constants import SCHEMA_FILE_GLOBS
from agent_actions.utils.file_utils import load_structured_file
from agent_actions.validation.base_validator import BaseValidator

logger = logging.getLogger(__name__)


def _find_refs(obj: dict[str, Any] | list[Any]) -> set[str]:
    """Find all $ref values in a schema object (recursive)."""
    refs: set[str] = set()
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            refs.add(obj["$ref"])
        for value in obj.values():
            refs.update(_find_refs(value))
    elif isinstance(obj, list):
        for item in obj:
            refs.update(_find_refs(item))
    return refs


# Keys whose immediate child *names* are user-defined identifiers (field names,
# definition names, pattern strings) rather than JSON Schema keywords.  We skip
# those names during suspicious-key detection to avoid false positives.
# Intentionally excludes items/allOf/anyOf/oneOf/additionalProperties — their
# values are sub-schemas (not user-field-name dicts), so we recurse into them
# normally and keyword typos inside them remain detectable.
_SCHEMA_CONTENT_KEYS = frozenset({"properties", "$defs", "definitions", "patternProperties"})


def _collect_all_keys(obj: Any) -> set[str]:
    """Collect all keys used in a schema object (recursive).

    For property-container keys (``properties``, ``$defs``, etc.) skips the
    immediate child *names* (which are user-defined field names, not schema
    keywords) but still recurses into each child's *sub-schema value* so that
    keyword typos inside property definitions remain detectable.
    """
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            if k in _SCHEMA_CONTENT_KEYS:
                # Skip child names (user field names / definition names) but
                # recurse into each child's sub-schema so typos are caught.
                if isinstance(v, dict):
                    for sub_schema in v.values():
                        keys |= _collect_all_keys(sub_schema)
                elif isinstance(v, list):
                    for item in v:
                        keys |= _collect_all_keys(item)
            else:
                keys |= _collect_all_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _collect_all_keys(item)
    return keys


class SchemaValidator(BaseValidator):
    """Validates schema files against JSON Schema meta-schema.

    Intentionally independent from SchemaLoader — this validates schema files
    (``.json``, ``.yml``, ``.yaml``) against the JSON Schema specification
    (structural correctness).  SchemaLoader handles runtime loading with
    multi-level resolution.
    """

    JSON_SCHEMA_RESERVED_KEYWORDS: set[str] = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "enum",
        "const",
        "multipleOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "format",
        "contentEncoding",
        "contentMediaType",
        "title",
        "description",
        "default",
        "examples",
        "definitions",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "$schema",
        "$id",
        "$ref",
    }

    def _process_schema_file(
        self, file_path: Path, schema_name: str, agent_name: str | None = "general"
    ) -> None:
        """Validate a single schema file and add errors to the instance."""
        display_name = f"schema '{schema_name}'"
        if agent_name:
            display_name += f" for agent '{agent_name}'"
        if not self._ensure_path_exists(file_path):
            self.add_error(
                f"Schema file '{file_path.name}' not found at path: {file_path}.",
                field=schema_name,
                value=str(file_path),
            )
            return
        if not self._is_file(file_path):
            self.add_error(
                f"Schema path '{file_path}' exists but is not a file.",
                field=schema_name,
                value=str(file_path),
            )
            return
        if not os.access(file_path, os.R_OK):
            self.add_error(
                f"Schema file '{file_path.name}' is not readable.",
                field=schema_name,
                value=str(file_path),
            )
            return
        try:
            schema_data = load_structured_file(file_path)
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            self.add_error(
                f"Invalid schema in {display_name} (file: {file_path.name}): {e}.",
                field=schema_name,
            )
            return
        except (OSError, ValueError) as e:
            self.add_error(
                f"Could not read or parse {display_name} (file: {file_path.name}): {e}.",
                field=schema_name,
            )
            return
        # Fields-format schemas (name/fields/id) are compiled to JSON Schema
        # at runtime by SchemaLoader.  Skip JSON Schema meta-validation here.
        if self._is_fields_format(schema_data):
            logger.debug(
                "Schema '%s' uses fields format; skipping JSON Schema checks.",
                file_path.name,
            )
            return
        if not self._is_valid_json_schema_structure(schema_data):
            self.add_error(
                f"{display_name} (file: {file_path.name}) does not appear to be "
                f"a valid JSON Schema document. It should have properties like "
                f"'type', 'properties', etc.",
                field=schema_name,
            )
            return
        try:
            self._validate_against_meta_schema_static(schema_data)
        except jsonschema.exceptions.SchemaError as e:
            self.add_error(
                f"{display_name} (file: {file_path.name}) has a malformed JSON Schema: {e.message}.",
                field=schema_name,
            )
            return
        except jsonschema.exceptions.ValidationError as e:
            error_path = " -> ".join(map(str, e.path))
            context_msg = f" (at path: '{error_path}')" if e.path else ""
            field_name = error_path if error_path else schema_name
            self.add_error(
                f"{display_name} (file: {file_path.name}) is not a valid "
                f"JSON Schema: {e.message}{context_msg}.",
                field=field_name,
            )
            return
        except (OSError, ValueError, TypeError) as e:
            logger.exception(
                "Unexpected error during meta-schema validation for %s",
                display_name,
                extra={
                    "file_path": str(file_path),
                    "schema_name": schema_name,
                    "agent_name": agent_name,
                },
            )
            self.add_error(
                f"Unexpected error during meta-schema validation for "
                f"{display_name} (file: {file_path.name}): {e}",
                field=schema_name,
            )
            return
        common_issues = self._check_common_schema_issues_static(schema_data, schema_name)
        for issue in common_issues:
            self.add_error(
                f"Issue in {display_name} (file: {file_path.name}): {issue}.",
                field=schema_name,
            )
        logger.debug("Successfully processed schema file: %s", file_path.name)

    @staticmethod
    def _is_valid_json_schema_structure(schema_data: Any) -> bool:
        """Return True if the dict appears to be a JSON Schema document."""
        if not isinstance(schema_data, dict):
            return False
        schema_keywords = {
            "type",
            "properties",
            "required",
            "items",
            "$schema",
            "definitions",
            "additionalProperties",
            "allOf",
            "anyOf",
            "oneOf",
        }
        return bool(set(schema_data.keys()) & schema_keywords)

    @staticmethod
    def _is_fields_format(schema_data: Any) -> bool:
        """Return True if the schema uses the internal fields format.

        Fields-format schemas have a ``fields`` list and are compiled to
        JSON Schema at runtime by :class:`SchemaLoader`.  They should not
        be validated against the JSON Schema meta-schema directly.
        """
        return (
            isinstance(schema_data, dict)
            and "fields" in schema_data
            and isinstance(schema_data.get("fields"), list)
        )

    @staticmethod
    def _validate_against_meta_schema_static(schema_data: dict[str, Any]) -> None:
        """Validate schema against the JSON Schema meta-schema; raises on failure."""
        validator_cls = jsonschema.validators.validator_for(schema_data)
        validator_cls.check_schema(schema_data)

    @classmethod
    def _check_common_schema_issues_static(
        cls, schema_data: dict[str, Any], schema_name: str
    ) -> list[str]:
        """Return list of common issue strings found in a JSON Schema document."""
        issues = []
        if "type" not in schema_data:
            issues.append(f"Missing 'type' property at the root level of schema '{schema_name}'.")
        if schema_data.get("type") == "object":
            properties = schema_data.get("properties", {})
            if not properties:
                issues.append(
                    f"Schema '{schema_name}' is 'object' type but has no defined 'properties'."
                )
            required = schema_data.get("required", [])
            if isinstance(required, list):
                undefined_props = [prop for prop in required if prop not in properties]
                if undefined_props:
                    issues.append(
                        f"Schema '{schema_name}' has required properties not "
                        f"defined in 'properties': {', '.join(undefined_props)}."
                    )
        if schema_data.get("type") == "array" and "items" not in schema_data:
            issues.append(f"Schema '{schema_name}' is 'array' type but 'items' is not defined.")
        if "definitions" in schema_data:
            definition_refs = _find_refs(schema_data)
            unused_defs = [
                def_name
                for def_name in schema_data.get("definitions", {})
                if f"#/definitions/{def_name}" not in definition_refs
                and f"#/$defs/{def_name}" not in definition_refs
            ]
            if unused_defs:
                issues.append(
                    f"Schema '{schema_name}' has unused definitions: {', '.join(unused_defs)}."
                )
        all_keys = _collect_all_keys(schema_data)
        unknown_keys = all_keys - cls.JSON_SCHEMA_RESERVED_KEYWORDS
        acceptable_custom = {
            "errorMessage",
            "readonly",
            "writeonly",
            "deprecated",
            "$defs",
        }
        suspicious_keys = unknown_keys - acceptable_custom
        if suspicious_keys:
            issues.append(
                f"Schema '{schema_name}' has potentially unknown/typo "
                f"properties: {', '.join(suspicious_keys)}."
            )
        return issues

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Validate schema files for a given agent in the specified directory."""
        agent_name = data.get("agent_name", "") if isinstance(data, dict) else ""
        target = f"schema:{agent_name}" if agent_name else "schema"

        if not self._prepare_validation(data, target=target):
            result = self._complete_validation()
            fire_event(
                DataValidationFailedEvent(
                    validator_type="SchemaValidator",
                    errors=[str(e) for e in self.get_errors()],
                )
            )
            return result

        schema_dir = data.get("schema_dir")
        schema_files_to_validate = data.get("schema_files")
        if not isinstance(agent_name, str) or not agent_name:
            self.add_error(
                "Data field 'agent_name' (string) is required.",
                field="agent_name",
            )
        if not isinstance(schema_dir, Path):
            self.add_error(
                "Data field 'schema_dir' (Path object) is required.",
                field="schema_dir",
            )
        if schema_files_to_validate is not None and (
            not isinstance(schema_files_to_validate, list)
            or not all(isinstance(f, str) for f in schema_files_to_validate)
        ):
            self.add_error(
                "Data field 'schema_files' must be a list of strings if provided.",
                field="schema_files",
            )
        if self.has_errors():
            result = self._complete_validation()
            fire_event(
                DataValidationFailedEvent(
                    validator_type="SchemaValidator",
                    errors=[str(e) for e in self.get_errors()],
                )
            )
            return result
        if not self._ensure_path_exists(schema_dir):
            self.add_error(
                f"Schema directory does not exist: {schema_dir}",
                field="schema_dir",
                value=str(schema_dir),
            )
            result = self._complete_validation()
            fire_event(
                DataValidationFailedEvent(
                    validator_type="SchemaValidator",
                    errors=[str(e) for e in self.get_errors()],
                )
            )
            return result
        if not self._is_directory(schema_dir):
            self.add_error(
                f"Schema path is not a directory: {schema_dir}",
                field="schema_dir",
                value=str(schema_dir),
            )
            result = self._complete_validation()
            fire_event(
                DataValidationFailedEvent(
                    validator_type="SchemaValidator",
                    errors=[str(e) for e in self.get_errors()],
                )
            )
            return result
        logger.debug(
            "Starting schema validation for agent '%s' in directory: %s", agent_name, schema_dir
        )
        if schema_files_to_validate:
            files_to_process = [schema_dir / fname for fname in schema_files_to_validate]
        else:
            # Validate every schema file independently (no stem-based
            # deduplication).  SchemaLoader handles name-collision warnings
            # at runtime; the validator checks structural correctness of
            # each file regardless.
            files_to_process = sorted(
                p for ext in SCHEMA_FILE_GLOBS for p in schema_dir.rglob(ext)
            )
            if not files_to_process:
                self.add_warning(
                    f"No schema files ({', '.join(SCHEMA_FILE_GLOBS)}) found in "
                    f"{schema_dir} for agent '{agent_name}'.",
                    field="schema_files",
                )
                result = self._complete_validation()
                fire_event(
                    DataValidationPassedEvent(
                        validator_type="SchemaValidator",
                        item_count=0,
                    )
                )
                return result
        for file_path in files_to_process:
            self._process_schema_file(file_path, file_path.name, agent_name)
        logger.debug("Schema validation complete for agent '%s'.", agent_name)

        result = self._complete_validation()

        if result:
            fire_event(
                DataValidationPassedEvent(
                    validator_type="SchemaValidator",
                    item_count=len(files_to_process),
                )
            )
        else:
            fire_event(
                DataValidationFailedEvent(
                    validator_type="SchemaValidator",
                    errors=[str(e) for e in self.get_errors()],
                )
            )

        return result

    def _check_type_compatibility(
        self,
        schema1_data: dict[str, Any],
        schema2_data: dict[str, Any],
        schema1_name: str,
        schema2_name: str,
    ) -> list[str]:
        """Check if schema types are compatible."""
        issues = []
        s1_type = schema1_data.get("type")
        s2_type = schema2_data.get("type")
        if s1_type != s2_type:
            issues.append(
                f"Root type mismatch: '{schema1_name}' is '{s1_type}', "
                f"'{schema2_name}' is '{s2_type}'."
            )
        return issues

    def _check_object_compatibility(
        self,
        schema1_data: dict[str, Any],
        schema2_data: dict[str, Any],
        schema1_name: str,
        schema2_name: str,
    ) -> list[str]:
        """Check if object schemas are compatible."""
        issues = []
        props1 = schema1_data.get("properties", {})
        props2 = schema2_data.get("properties", {})
        req2 = set(schema2_data.get("required", []))
        missing = req2 - set(props1.keys())
        if missing:
            issues.append(
                f"'{schema2_name}' requires properties not defined in '{schema1_name}': {missing}."
            )
        common_props = set(props1.keys()) & set(props2.keys())
        for prop_name in common_props:
            prop1_detail = props1.get(prop_name, {})
            prop2_detail = props2.get(prop_name, {})
            if prop1_detail.get("type") != prop2_detail.get("type"):
                issues.append(
                    f"Property '{prop_name}' type mismatch: "
                    f"'{schema1_name}' is '{prop1_detail.get('type')}', "
                    f"'{schema2_name}' is '{prop2_detail.get('type')}'."
                )
        return issues

    def check_schema_compatibility(
        self,
        schema1_data: dict[str, Any],
        schema2_data: dict[str, Any],
        schema1_name: str = "Schema 1",
        schema2_name: str = "Schema 2",
    ) -> bool:
        """Return True if two schemas are compatible; clears and repopulates errors."""
        self.clear_errors()
        self.clear_warnings()
        logger.debug(
            "Checking schema compatibility between '%s' and '%s'.", schema1_name, schema2_name
        )
        issues = self._check_type_compatibility(
            schema1_data, schema2_data, schema1_name, schema2_name
        )
        s1_type = schema1_data.get("type")
        s2_type = schema2_data.get("type")
        if s1_type == "object" and s2_type == "object":
            issues.extend(
                self._check_object_compatibility(
                    schema1_data, schema2_data, schema1_name, schema2_name
                )
            )
        for issue in issues:
            self.add_error(issue)
        return not self.has_errors()
