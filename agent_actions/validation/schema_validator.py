"""
Schema validation utilities.

This module provides utilities for validating schema files and
ensuring they meet the required format and constraints.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import jsonschema

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    DataValidationFailedEvent,
    DataValidationPassedEvent,
    DataValidationStartedEvent,
)
from agent_actions.validation.base_validator import BaseValidator

logger = logging.getLogger(__name__)


def _find_refs(obj: Union[Dict[str, Any], List[Any]]) -> Set[str]:
    """Find all $ref values in a schema object (recursive)."""
    refs: Set[str] = set()
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            refs.add(obj["$ref"])
        for value in obj.values():
            refs.update(_find_refs(value))
    elif isinstance(obj, list):
        for item in obj:
            refs.update(_find_refs(item))
    return refs


def _collect_all_keys(obj: Union[Dict[str, Any], List[Any]]) -> Set[str]:
    """Collect all keys used in a schema object (recursive)."""
    keys: Set[str] = set()
    if isinstance(obj, dict):
        keys.update(obj.keys())
        for value in obj.values():
            keys.update(_collect_all_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_all_keys(item))
    return keys


class SchemaValidator(BaseValidator):
    """
    Handles schema validation operations by inheriting from BaseValidator.
    """

    JSON_SCHEMA_RESERVED_KEYWORDS: Set[str] = {
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
        self, file_path: Path, schema_name: str, agent_name: Optional[str] = "general"
    ) -> None:
        """
        Validates a single schema file and adds errors to the instance.
        Corresponds to the old _validate_schema_file but uses self.add_error.
        """
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
            with open(file_path, "r", encoding="utf-8") as f:
                schema_data = json.load(f)
        except json.JSONDecodeError as e:
            self.add_error(
                f"Invalid JSON in {display_name} (file: {file_path.name}): {e}.",
                field=schema_name,
            )
            return
        except (OSError, ValueError) as e:
            self.add_error(
                f"Could not read or parse {display_name} (file: {file_path.name}): {e}.",
                field=schema_name,
            )
            return
        if not self._is_valid_json_schema_structure(schema_data):
            self.add_error(
                f"{display_name} (file: {file_path.name}) does not appear to be "
                f"a valid JSON Schema document. It should have properties like "
                f"'type', 'properties', etc.",
                field=schema_name,
            )
        try:
            self._validate_against_meta_schema_static(schema_data)
        except jsonschema.exceptions.ValidationError as e:
            error_path = " -> ".join(map(str, e.path))
            context_msg = f" (at path: '{error_path}')" if e.path else ""
            field_name = error_path if error_path else schema_name
            self.add_error(
                f"{display_name} (file: {file_path.name}) is not a valid "
                f"JSON Schema: {e.message}{context_msg}.",
                field=field_name,
            )
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
        common_issues = self._check_common_schema_issues_static(schema_data, schema_name)
        for issue in common_issues:
            self.add_error(
                f"Issue in {display_name} (file: {file_path.name}): {issue}.",
                field=schema_name,
            )
        logger.debug("Successfully processed schema file: %s", file_path.name)

    @staticmethod
    def _is_valid_json_schema_structure(schema_data: Dict[str, Any]) -> bool:
        """Checks if a dictionary appears to be a JSON Schema document."""
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
    def _validate_against_meta_schema_static(schema_data: Dict[str, Any]) -> None:
        """Validates a schema against the JSON Schema meta-schema. Raises error on failure."""
        validator_cls = jsonschema.validators.validator_for(schema_data)
        validator_cls.check_schema(schema_data)

    @classmethod
    def _check_common_schema_issues_static(
        cls, schema_data: Dict[str, Any], schema_name: str
    ) -> List[str]:
        """Checks for common issues in JSON Schema documents.

        Returns list of issue strings.
        """
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
            "examples",
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

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validates schema files for a given agent in a specified directory.

        Args:
            data: A dictionary containing:
                - "agent_name" (str): Name of the agent.
                - "schema_dir" (Path): Directory containing the agent's schema
                  files (e.g., *.json).
                - "schema_files" (Optional[List[str]]): Specific schema
                  filenames to validate. If None, will attempt to find all
                  .json files.
            config: Optional. Could be used for future extensions, e.g.,
                specifying schema dialect.

        Returns:
            bool: True if all schema validations pass, False otherwise.
        """
        agent_name = data.get("agent_name", "") if isinstance(data, dict) else ""
        target = f"schema:{agent_name}" if agent_name else "schema"

        # Fire validation started event
        fire_event(
            DataValidationStartedEvent(
                validator_type="SchemaValidator",
                target=target,
            )
        )

        if not self._prepare_validation(data, target=target):
            result = self._complete_validation()
            # Fire validation failed event
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
            files_to_process = list(schema_dir.glob("*.json"))
            if not files_to_process:
                self.add_warning(
                    f"No .json schema files found in {schema_dir} for agent '{agent_name}'.",
                    field="schema_files",
                )
                result = self._complete_validation()
                # No files means validation passed (with warning)
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

        # Fire validation result event
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
        schema1_data: Dict[str, Any],
        schema2_data: Dict[str, Any],
        schema1_name: str,
        schema2_name: str,
    ) -> List[str]:
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
        schema1_data: Dict[str, Any],
        schema2_data: Dict[str, Any],
        schema1_name: str,
        schema2_name: str,
    ) -> List[str]:
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
        schema1_data: Dict[str, Any],
        schema2_data: Dict[str, Any],
        schema1_name: str = "Schema 1",
        schema2_name: str = "Schema 2",
    ) -> bool:
        """
        Validates that two schemas are compatible.

        Adds errors to the instance if not. This method is separate from the
        main file-based validation flow. It CLEARS existing errors on the
        instance before running.
        """
        self.clear_errors()
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
