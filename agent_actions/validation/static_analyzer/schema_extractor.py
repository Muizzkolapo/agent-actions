"""Extract output schemas from agent configurations.

Handles schema extraction from:
- LLM agents: from `schema` or `output_schema` field
- Tool/UDF agents: from UDF_REGISTRY json_output_schema
- Non-JSON agents: fallback to content field
"""

from pathlib import Path
from typing import Any, Dict, Optional, Set

import yaml

from .data_flow_graph import InputSchema, OutputSchema


class SchemaExtractor:
    """Extracts output schemas from various agent types.

    Handles:
    - LLM agents: from `schema` or `output_schema` field
    - Tool/UDF agents: from UDF_REGISTRY json_output_schema
    - Non-JSON agents: assume `content` field

    Example:
        extractor = SchemaExtractor(udf_registry=UDF_REGISTRY)

        schema = extractor.extract_schema(agent_config)
        print(schema.available_fields)  # {'summary', 'facts'}
    """

    def __init__(
        self,
        udf_registry: Optional[Dict[str, Any]] = None,
        schema_dir: Optional[Path] = None,
    ) -> None:
        """Initialize the schema extractor.

        Args:
            udf_registry: UDF_REGISTRY from udf_management module for tool schemas
            schema_dir: Path to schema directory (defaults to cwd/schema)
        """
        self.udf_registry = udf_registry or {}
        self.schema_dir = schema_dir or Path.cwd() / "schema"

    def extract_schema(
        self,
        agent_config: Dict[str, Any],
        schema_loader: Optional[Any] = None,
    ) -> OutputSchema:
        """Extract output schema from agent config.

        Args:
            agent_config: Agent configuration dictionary
            schema_loader: Optional SchemaLoader for loading external schemas

        Returns:
            OutputSchema with extracted field information
        """
        output = OutputSchema()

        # Determine agent type
        kind = agent_config.get("kind", "llm")
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_schema(agent_config, output)
        else:
            self._extract_llm_schema(agent_config, output, schema_loader)

        # Apply context_scope directives (common to all agents)
        self._apply_context_scope(agent_config, output)

        return output

    def extract_input_schema(
        self,
        agent_config: Dict[str, Any],
    ) -> InputSchema:
        """Extract input schema from agent config.

        For tools: from UDF_REGISTRY json_schema (input schema)
        For LLMs: inferred from template variables (marked as template_based)

        Args:
            agent_config: Agent configuration dictionary

        Returns:
            InputSchema with extracted field information
        """
        input_schema = InputSchema()

        # Determine agent type
        kind = agent_config.get("kind", "llm")
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_input_schema(agent_config, input_schema)
        else:
            # LLM agents - inputs are inferred from templates
            input_schema.is_template_based = True
            # We could extract required template vars here, but that's
            # already handled by ReferenceExtractor

        return input_schema

    def _extract_tool_input_schema(
        self,
        config: Dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Extract input schema from tool/UDF agent."""
        impl = config.get("impl", "")

        # Try to get input schema from UDF registry
        if impl and impl in self.udf_registry:
            udf_info = self.udf_registry[impl]
            json_schema = udf_info.get("json_schema")  # Input schema
            if json_schema:
                input_schema.json_schema = json_schema
                # Extract required and optional fields
                self._extract_input_fields_from_json_schema(json_schema, input_schema)
                return

        # Check for inline input_schema on tool config
        schema_def = config.get("input_schema")
        if schema_def and isinstance(schema_def, dict):
            input_schema.json_schema = schema_def
            self._extract_input_fields_from_json_schema(schema_def, input_schema)
        else:
            # Tool without explicit input schema
            input_schema.is_dynamic = True

    def _extract_input_fields_from_json_schema(
        self,
        schema: Dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Extract required and optional fields from JSON schema.

        Args:
            schema: JSON schema dictionary
            input_schema: InputSchema to populate
        """
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        for field_name in properties.keys():
            if field_name in required:
                input_schema.required_fields.add(field_name)
            else:
                input_schema.optional_fields.add(field_name)

    def _extract_llm_schema(  # pylint: disable=too-many-branches
        self,
        config: Dict[str, Any],
        output: OutputSchema,
        schema_loader: Optional[Any],
    ) -> None:
        """Extract schema from LLM agent."""
        # Get schema definition (supports 'schema', 'output_schema', and 'schema_name')
        schema_def = config.get("schema") or config.get("output_schema")
        schema_name = config.get("schema_name")

        # If no inline schema but has schema_name, try to load external schema
        if not schema_def and schema_name:
            # Try direct loading from schema directory first (most reliable)
            loaded = self._load_schema_from_dir(schema_name)
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self._extract_fields_from_json_schema(loaded)
                return

            # Fall back to schema_loader if provided
            if schema_loader:
                try:
                    loaded = schema_loader.load_schema(schema_name)
                    output.json_schema = loaded
                    output.schema_fields = self._extract_fields_from_json_schema(loaded)
                    return
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # Schema loading failed - will fall through to schemaless

        if not schema_def:
            # Check json_mode - if enabled, agent should have schema
            json_mode = config.get("json_mode", True)
            if not json_mode:
                # Non-JSON mode - freeform output
                output.is_schemaless = True
                output.schema_fields.add("content")
                output.schema_fields.add("raw_response")
                return

            # JSON mode without schema - mark as schemaless for warning
            output.is_schemaless = True
            output.schema_fields.add("content")
            return

        # Handle different schema formats
        if isinstance(schema_def, str):
            # Schema reference (external file) - try direct loading first
            loaded = self._load_schema_from_dir(schema_def)
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self._extract_fields_from_json_schema(loaded)
            elif schema_loader:
                # Fall back to schema_loader
                try:
                    loaded = schema_loader.load_schema(schema_def)
                    output.json_schema = loaded
                    output.schema_fields = self._extract_fields_from_json_schema(loaded)
                except Exception:  # pylint: disable=broad-exception-caught
                    output.is_dynamic = True
            else:
                output.is_dynamic = True
        elif isinstance(schema_def, dict):
            # Inline schema
            output.json_schema = schema_def
            output.schema_fields = self._extract_fields_from_json_schema(schema_def)
        elif isinstance(schema_def, list):
            # Array of field definitions
            output.json_schema = {"type": "array", "items": schema_def}
            for item in schema_def:
                if isinstance(item, dict) and "id" in item:
                    output.schema_fields.add(item["id"])
                elif isinstance(item, dict) and "name" in item:
                    output.schema_fields.add(item["name"])

    def _extract_tool_schema(
        self,
        config: Dict[str, Any],
        output: OutputSchema,
    ) -> None:
        """Extract schema from tool/UDF agent."""
        impl = config.get("impl", "")

        # Try to get schema from UDF registry
        if impl and impl in self.udf_registry:
            udf_info = self.udf_registry[impl]
            json_schema = udf_info.get("json_output_schema")
            if json_schema:
                output.json_schema = json_schema
                output.schema_fields = self._extract_fields_from_json_schema(json_schema)
                return

        # Check for inline schema on tool config
        schema_def = config.get("schema") or config.get("output_schema")
        if schema_def:
            if isinstance(schema_def, dict):
                output.json_schema = schema_def
                output.schema_fields = self._extract_fields_from_json_schema(schema_def)
            else:
                output.is_dynamic = True
        else:
            # Tool without schema - could return anything
            output.is_schemaless = True

    def _apply_context_scope(self, config: Dict[str, Any], output: OutputSchema) -> None:
        """Apply context_scope directives to output schema.

        Handles:
        - observe: fields passed through from input
        - passthrough: fields included in output
        - drops: fields excluded from output
        """
        # Add observe fields (pass-through from input)
        observe = config.get("observe", [])
        for ref in observe:
            # Observe can be "field" or "agent.field" - extract field name
            field_name = self._extract_field_name(ref)
            if field_name:
                output.observe_fields.add(field_name)

        # Add dropped fields
        drops = config.get("drops", [])
        for ref in drops:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.dropped_fields.add(field_name)

        # Handle context_scope directives
        context_scope = config.get("context_scope", {})

        # Passthrough fields
        passthrough = context_scope.get("passthrough", [])
        for ref in passthrough:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.passthrough_fields.add(field_name)

        # Additional observe from context_scope
        scope_observe = context_scope.get("observe", [])
        for ref in scope_observe:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.observe_fields.add(field_name)

        # Additional drops from context_scope
        scope_drops = context_scope.get("drop", []) or context_scope.get("drops", [])
        for ref in scope_drops:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.dropped_fields.add(field_name)

        # Handle return_collection - adds input_data field
        if config.get("return_collection"):
            output.schema_fields.add("input_data")

    def _extract_fields_from_json_schema(  # pylint: disable=too-many-branches
        self, schema: Dict[str, Any]
    ) -> Set[str]:
        """Extract top-level field names from JSON schema.

        Handles:
        - Standard object schemas with properties
        - Shorthand notation (name: type)
        - Nested definitions

        Args:
            schema: JSON schema dictionary

        Returns:
            Set of field names
        """
        fields: Set[str] = set()

        # Check schema type
        schema_type = schema.get("type", "object")

        if schema_type == "object":
            # Standard object schema
            properties = schema.get("properties", {})
            fields.update(properties.keys())
        elif schema_type == "array":
            # Array schema - the wrapper name becomes a field
            name = schema.get("name", "items")
            fields.add(name)

        # Handle shorthand notation: {field_name: type_string}
        # These are fields that aren't in standard JSON schema keywords
        json_schema_keywords = {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "description",
            "name",
            "$schema",
            "definitions",
            "$defs",
            "title",
            "default",
            "enum",
            "const",
            "allOf",
            "anyOf",
            "oneOf",
            "not",
            "if",
            "then",
            "else",
            "minItems",
            "maxItems",
            "minimum",
            "maximum",
            "pattern",
            "format",
            "minLength",
            "maxLength",
        }

        for key, value in schema.items():
            if key not in json_schema_keywords:
                # Likely a field definition in shorthand
                if isinstance(value, str):
                    # Shorthand: field_name: "string"
                    fields.add(key)
                elif isinstance(value, dict):
                    # Could be a field with type definition or nested schema
                    if "type" in value or any(k in value for k in ["properties", "items"]):
                        fields.add(key)

        # Handle unified schema format with 'fields' array
        if "fields" in schema:
            for field_def in schema["fields"]:
                if isinstance(field_def, dict):
                    field_id = field_def.get("id") or field_def.get("name")
                    if field_id:
                        fields.add(field_id)

        # Handle array schema with items.properties (extract nested fields)
        if schema_type == "array" and "items" in schema:
            items = schema["items"]
            if isinstance(items, dict) and "properties" in items:
                fields.update(items["properties"].keys())

        return fields

    def _load_schema_from_dir(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Load a schema from the schema directory.

        Uses the same approach as the docs parser for reliable schema loading.

        Args:
            schema_name: Name of the schema file (without extension)

        Returns:
            Loaded schema dict or None if not found
        """
        if not self.schema_dir or not self.schema_dir.exists():
            return None

        # Try .yml first, then .yaml
        for ext in ["yml", "yaml"]:
            schema_file = self.schema_dir / f"{schema_name}.{ext}"
            if schema_file.exists():
                try:
                    with open(schema_file, "r", encoding="utf-8") as f:
                        return yaml.safe_load(f)
                except (yaml.YAMLError, OSError):
                    return None

        return None

    def _extract_field_name(self, reference: str) -> Optional[str]:
        """Extract field name from a reference.

        Handles formats:
        - 'field' -> 'field'
        - 'agent.field' -> 'field'
        - 'agent.nested.field' -> 'nested'

        Args:
            reference: Reference string

        Returns:
            Field name or None
        """
        if not reference:
            return None

        if "." in reference:
            # Format: agent.field or agent.nested.field
            parts = reference.split(".")
            if len(parts) >= 2:
                return parts[1]  # Return first field after agent
        else:
            return reference

        return None

    def extract_from_workflow(
        self,
        workflow_config: Dict[str, Any],
        schema_loader: Optional[Any] = None,
    ) -> Dict[str, OutputSchema]:
        """Extract schemas from all agents in a workflow.

        Args:
            workflow_config: Full workflow configuration
            schema_loader: Optional schema loader for external schemas

        Returns:
            Dict mapping agent names to their output schemas
        """
        schemas: Dict[str, OutputSchema] = {}

        actions = workflow_config.get("actions", [])
        for action in actions:
            name = action.get("name", "unknown")
            schemas[name] = self.extract_schema(action, schema_loader)

        return schemas
