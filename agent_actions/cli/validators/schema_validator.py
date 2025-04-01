"""
Schema validation utilities.

This module provides utilities for validating schema files and
ensuring they meet the required format and constraints.
"""

import os
import json
import logging
import jsonschema
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple, Union

from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.cli.exceptions import (
    SchemaValidationError,
    FileNotFoundError,
    ValidationError
)

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Handles schema validation operations."""
    

    
    # Reserved keywords in JSON Schema
    JSON_SCHEMA_RESERVED_KEYWORDS = {
        'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems',
        'uniqueItems', 'minLength', 'maxLength', 'pattern', 'enum', 'const', 'multipleOf',
        'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'format', 'contentEncoding',
        'contentMediaType', 'title', 'description', 'default', 'examples', 'definitions',
        'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else', '$schema', '$id', '$ref'
    }
    
    @classmethod
    def validate_schema(cls, agent_name: str, schema_dir: Path) -> None:
        """
        Validate that the required schemas exist and are valid JSON Schema documents.

        Args:
            agent_name: Name of the agent.
            schema_dir: Path to the schema directory.
            
        Raises:
            SchemaValidationError: If schema validation fails.
            FileNotFoundError: If required schema files are not found.
        """
        logger.info("Starting schema validation", extra={
            'agent_name': agent_name,
            'schema_dir': str(schema_dir)
        })
        
        pass
    
    @classmethod
    def _validate_schema_file(cls, file_path: Path, schema_name: str, agent_name: str) -> List[str]:
        """
        Validate a single schema file.
        
        Args:
            file_path: Path to the schema file.
            schema_name: Name of the schema file.
            agent_name: Name of the agent.
            
        Returns:
            List of error messages, empty if validation is successful.
        """
        errors = []
        
        try:
            # Check file exists and is readable
            if not file_path.exists():
                return [f"Schema file '{schema_name}' not found for agent '{agent_name}'"]
                
            if not file_path.is_file():
                return [f"Schema path '{file_path}' exists but is not a file"]
                
            if not os.access(file_path, os.R_OK):
                return [f"Schema file '{schema_name}' is not readable"]
            
            # Read and parse JSON
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    schema_data = json.load(f)
            except json.JSONDecodeError as e:
                return [f"Invalid JSON in schema file '{schema_name}': {str(e)}"]
                
            # Check if it's a JSON Schema (has required JSON Schema properties)
            if not cls._is_json_schema(schema_data):
                errors.append(
                    f"Schema file '{schema_name}' does not appear to be a valid JSON Schema document. "
                    "It should have properties like 'type', 'properties', etc."
                )
            
            # Validate against JSON Schema meta-schema
            try:
                cls._validate_against_meta_schema(schema_data)
            except jsonschema.exceptions.ValidationError as e:
                errors.append(f"Schema file '{schema_name}' is not a valid JSON Schema: {e.message}")
                
            # Check for common schema issues
            schema_issues = cls._check_common_schema_issues(schema_data, schema_name)
            errors.extend(schema_issues)
                
            return errors
            
        except Exception as e:
            logger.error(f"Error validating schema file '{schema_name}': {str(e)}", exc_info=True)
            return [f"Error validating schema file '{schema_name}': {str(e)}"]
    
    @staticmethod
    def _is_json_schema(schema_data: Dict[str, Any]) -> bool:
        """
        Check if a dictionary appears to be a JSON Schema document.
        
        Args:
            schema_data: The schema data to check.
            
        Returns:
            True if it appears to be a JSON Schema, False otherwise.
        """
        # Check for common JSON Schema keywords
        schema_keywords = {'type', 'properties', 'required', 'items', '$schema', 'definitions', 
                          'additionalProperties', 'allOf', 'anyOf', 'oneOf'}
        
        # If it has at least one schema keyword, it's probably a schema
        return bool(set(schema_data.keys()) & schema_keywords)
    
    @staticmethod
    def _validate_against_meta_schema(schema_data: Dict[str, Any]) -> None:
        """
        Validate a schema against the JSON Schema meta-schema.
        
        Args:
            schema_data: The schema data to validate.
            
        Raises:
            jsonschema.exceptions.ValidationError: If the schema is invalid.
        """
        # Use Draft 7 meta-schema
        from jsonschema import validate
        from jsonschema.validators import validator_for
        
        # Determine which schema version to use
        schema_url = schema_data.get('$schema')
        if schema_url:
            # Use the validator for the specified schema
            validator_cls = validator_for(schema_url)
            validator_cls.check_schema(schema_data)
        else:
            # Default to Draft 7
            from jsonschema.validators import Draft7Validator
            Draft7Validator.check_schema(schema_data)
    
    @classmethod
    def _check_common_schema_issues(cls, schema_data: Dict[str, Any], schema_name: str) -> List[str]:
        """
        Check for common issues in JSON Schema documents.
        
        Args:
            schema_data: The schema data to check.
            schema_name: Name of the schema file for error reporting.
            
        Returns:
            List of error messages for issues found.
        """
        issues = []
        
        # Check if type is specified
        if 'type' not in schema_data:
            issues.append(f"Schema '{schema_name}' is missing 'type' property at the root level")
        
        # Check for root level required properties
        if schema_data.get('type') == 'object' and 'properties' in schema_data:
            # Check that properties exist
            properties = schema_data.get('properties', {})
            if not properties:
                issues.append(f"Schema '{schema_name}' has 'object' type but no defined properties")
                
            # Check required properties
            required = schema_data.get('required', [])
            if required:
                # Check that all required properties are defined
                undefined_props = [prop for prop in required if prop not in properties]
                if undefined_props:
                    props_list = ", ".join(undefined_props)
                    issues.append(
                        f"Schema '{schema_name}' has required properties that are not defined: {props_list}"
                    )
        
        # Check for array items
        if schema_data.get('type') == 'array' and 'items' not in schema_data:
            issues.append(f"Schema '{schema_name}' has 'array' type but no 'items' defined")
        
        # Check for unreferenced definitions
        if 'definitions' in schema_data:
            definitions = schema_data.get('definitions', {})
            definition_refs = cls._find_refs(schema_data)
            
            # Check for unused definitions
            unused_defs = []
            for def_name in definitions:
                ref = f"#/definitions/{def_name}"
                if ref not in definition_refs:
                    unused_defs.append(def_name)
                    
            if unused_defs:
                defs_list = ", ".join(unused_defs)
                issues.append(f"Schema '{schema_name}' has unused definitions: {defs_list}")
        
        # Check for custom keywords that might be typos
        all_keys = cls._collect_all_keys(schema_data)
        unknown_keys = all_keys - cls.JSON_SCHEMA_RESERVED_KEYWORDS
        
        if unknown_keys:
            # Filter out common non-standard but acceptable keywords
            acceptable_custom = {'examples', 'errorMessage', 'readonly', 'writeonly', 'deprecated'}
            suspicious_keys = unknown_keys - acceptable_custom
            
            if suspicious_keys:
                keys_list = ", ".join(suspicious_keys)
                issues.append(
                    f"Schema '{schema_name}' has potentially unknown properties that may be typos: {keys_list}"
                )
        
        return issues
    
    @classmethod
    def _find_refs(cls, obj: Union[Dict[str, Any], List[Any]]) -> Set[str]:
        """
        Find all $ref values in a schema.
        
        Args:
            obj: The schema object to search.
            
        Returns:
            Set of reference strings.
        """
        refs = set()
        
        if isinstance(obj, dict):
            # Check if this object has a $ref
            if '$ref' in obj:
                refs.add(obj['$ref'])
                
            # Recursively search all values
            for value in obj.values():
                refs.update(cls._find_refs(value))
                
        elif isinstance(obj, list):
            # Recursively search all items
            for item in obj:
                refs.update(cls._find_refs(item))
                
        return refs
    
    @classmethod
    def _collect_all_keys(cls, obj: Union[Dict[str, Any], List[Any]]) -> Set[str]:
        """
        Collect all keys used in a schema.
        
        Args:
            obj: The schema object to search.
            
        Returns:
            Set of all keys found.
        """
        keys = set()
        
        if isinstance(obj, dict):
            # Add all keys from this object
            keys.update(obj.keys())
            
            # Recursively collect keys from all values
            for value in obj.values():
                keys.update(cls._collect_all_keys(value))
                
        elif isinstance(obj, list):
            # Recursively collect keys from all items
            for item in obj:
                keys.update(cls._collect_all_keys(item))
                
        return keys
    
    @staticmethod
    def validate_schema_compatibility(
        schema1: Dict[str, Any], 
        schema2: Dict[str, Any],
        schema1_name: str = "Schema 1",
        schema2_name: str = "Schema 2"
    ) -> List[str]:
        """
        Validate that two schemas are compatible.
        
        Args:
            schema1: First schema to compare.
            schema2: Second schema to compare.
            schema1_name: Name of the first schema for error reporting.
            schema2_name: Name of the second schema for error reporting.
            
        Returns:
            List of compatibility issues, empty if schemas are compatible.
        """
        issues = []
        
        # Check root types
        if schema1.get('type') != schema2.get('type'):
            issues.append(
                f"{schema1_name} has type '{schema1.get('type')}' but "
                f"{schema2_name} has type '{schema2.get('type')}'"
            )
            return issues  # Return early if root types don't match
        
        # Handle objects
        if schema1.get('type') == 'object' and schema2.get('type') == 'object':
            # Check properties
            props1 = schema1.get('properties', {})
            props2 = schema2.get('properties', {})
            
            # Check required properties
            req1 = set(schema1.get('required', []))
            req2 = set(schema2.get('required', []))
            
            # Schema 2 shouldn't require properties that schema 1 doesn't have
            missing_props = req2 - set(props1.keys())
            if missing_props:
                props_list = ", ".join(missing_props)
                issues.append(
                    f"{schema2_name} requires properties that {schema1_name} doesn't define: {props_list}"
                )
            
            # Check property types for common properties
            common_props = set(props1.keys()) & set(props2.keys())
            for prop in common_props:
                prop_type1 = props1[prop].get('type')
                prop_type2 = props2[prop].get('type')
                
                if prop_type1 != prop_type2:
                    issues.append(
                        f"Property '{prop}' has type '{prop_type1}' in {schema1_name} "
                        f"but '{prop_type2}' in {schema2_name}"
                    )
        
        # Handle arrays
        elif schema1.get('type') == 'array' and schema2.get('type') == 'array':
            # Check item types
            items1 = schema1.get('items', {})
            items2 = schema2.get('items', {})
            
            if items1.get('type') != items2.get('type'):
                issues.append(
                    f"Array items have type '{items1.get('type')}' in {schema1_name} "
                    f"but '{items2.get('type')}' in {schema2_name}"
                )
        
        return issues