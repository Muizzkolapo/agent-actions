"""
Extract output schemas from action configurations.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent_actions.tooling.docs.scanner import ProjectScanner
from agent_actions.output.response.loader import SchemaLoader

from .data_flow_graph import InputSchema, OutputSchema


class SchemaExtractor:
    """Extracts output schemas from various action types.

    Handles:
    - LLM actions: from `schema` field
    - Tool/UDF actions: from Python files via AST parsing (using impl field)
    - Non-JSON actions: assume `content` field

    Example:
        extractor = SchemaExtractor(project_root=Path.cwd())

        schema = extractor.extract_schema(agent_config)
        print(schema.available_fields)  # {'summary', 'facts'}
    """

    def __init__(
        self,
        udf_registry: Optional[Dict[str, Any]] = None,
        schema_dir: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        """Initialize the schema extractor.

        Args:
            udf_registry: UDF_REGISTRY from udf_management module (legacy, optional)
            schema_dir: Path to schema directory (defaults to cwd/schema)
            project_root: Project root for scanning tool functions
        """
        self.udf_registry = udf_registry or {}
        self.schema_dir = schema_dir or Path.cwd() / "schema"
        self.project_root = project_root or Path.cwd()
        self._tool_schemas: Optional[Dict[str, Any]] = None

    def _get_tool_schemas(self) -> Dict[str, Any]:
        """Lazy-load tool schemas from Python files using ProjectScanner."""
        if self._tool_schemas is None:
            scanner = ProjectScanner(str(self.project_root))
            self._tool_schemas = scanner.scan_tool_functions()
        return self._tool_schemas

    def _convert_fields_to_json_schema(self, fields: List[Dict[str, str]]) -> Dict[str, Any]:
        """Convert scanner field format to JSON schema format."""
        properties = {}
        required = []

        for field in fields:
            field_name = field["name"]
            field_type = field.get("type", "string")

            # Map Python types to JSON schema types
            json_type = self._python_type_to_json_type(field_type)
            properties[field_name] = {"type": json_type}

            if field.get("required", True):
                required.append(field_name)

        return {"type": "object", "properties": properties, "required": required}

    def _python_type_to_json_type(self, python_type: str) -> str:
        """Map Python type annotation to JSON schema type."""
        type_map = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
            "List": "array",
            "Dict": "object",
            "Any": "string",
            "None": "null",
        }

        # Handle simple types
        for py_type, json_type in type_map.items():
            if python_type == py_type or python_type.startswith(f"{py_type}["):
                return json_type

        # Handle Optional types
        if python_type.startswith("Optional["):
            inner = python_type[9:-1]
            return self._python_type_to_json_type(inner)

        # Default to string for complex types
        return "string"

    def extract_schema(
        self,
        agent_config: Dict[str, Any],
        schema_loader: Optional[Any] = None,
    ) -> OutputSchema:
        """Extract output schema from action config.

        Args:
            agent_config: Action configuration dictionary
            schema_loader: Optional SchemaLoader for loading external schemas

        Returns:
            OutputSchema with extracted field information
        """
        output = OutputSchema()

        # Determine action type
        kind = agent_config.get("kind", "llm")
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_schema(agent_config, output)
        else:
            self._extract_llm_schema(agent_config, output, schema_loader)

        # Apply context_scope directives (common to all actions)
        self._apply_context_scope(agent_config, output)

        return output

    def extract_input_schema(
        self,
        agent_config: Dict[str, Any],
        reference_extractor: Optional[Any] = None,
    ) -> InputSchema:
        """Extract input schema from action config.

        For tools: from Python files via AST parsing (using impl field)
        For LLMs: from template references and context_scope

        Args:
            agent_config: Action configuration dictionary
            reference_extractor: ReferenceExtractor for LLM template analysis

        Returns:
            InputSchema with extracted field information
        """
        input_schema = InputSchema()

        # Determine action type
        kind = agent_config.get("kind", "llm")
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_input_schema(agent_config, input_schema)
        else:
            # LLM actions - extract from template references and context_scope
            self._extract_llm_input_schema(agent_config, input_schema, reference_extractor)

        return input_schema

    def _extract_llm_input_schema(
        self,
        config: Dict[str, Any],
        input_schema: InputSchema,
        reference_extractor: Optional[Any] = None,
    ) -> None:
        """Extract input schema from LLM action config.

        Resolves inputs from:
        - Template references ({{ action.field }})
        - context_scope observe fields
        - Dependencies
        """
        # Import here to avoid circular imports
        if reference_extractor is None:
            from .reference_extractor import (
                ReferenceExtractor,
            )

            reference_extractor = ReferenceExtractor()

        # Extract all field references from the action config
        requirements = reference_extractor.extract_from_agent(config)

        # Add referenced fields as required inputs
        for req in requirements:
            # Format: "action.field" or just "field"
            if req.source_agent and req.field_path:
                field_ref = f"{req.source_agent}.{req.field_path}"
            else:
                field_ref = req.field_path or ""

            if field_ref:
                input_schema.required_fields.add(field_ref)

        return input_schema

    def _extract_tool_input_schema(
        self,
        config: Dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Extract input schema from tool/UDF action.

        Tries the following sources in order:
        1. Python files via scanner (AST parsing)
        2. UDF registry (for UDFs with input_type - legacy)
        3. Inline input_schema in tool config
        4. context_scope (new style - infer from observe declarations)
        """
        # impl may be stored as 'impl' or 'model_name' depending on config processing
        impl = config.get("impl") or config.get("model_name") or ""

        # Try to get schema from Python files via scanner (using impl as function name)
        if impl:
            tool_schemas = self._get_tool_schemas()
            if impl in tool_schemas:
                tool_info = tool_schemas[impl]
                tool_input_schema = tool_info.get("input_schema")
                if tool_input_schema and tool_input_schema.get("fields"):
                    json_schema = self._convert_fields_to_json_schema(tool_input_schema["fields"])
                    input_schema.json_schema = json_schema
                    self._extract_input_fields_from_json_schema(json_schema, input_schema)
                    return

        # Fallback: try UDF registry (for backward compatibility with input_type)
        impl_key = impl.lower() if impl else ""
        if impl_key and impl_key in self.udf_registry:
            udf_info = self.udf_registry[impl_key]
            json_schema = udf_info.get("json_schema")  # Input schema (may be None for new style)
            if json_schema:
                input_schema.json_schema = json_schema
                self._extract_input_fields_from_json_schema(json_schema, input_schema)
                return

        # Check for inline input_schema on tool config
        schema_def = config.get("input_schema")
        if schema_def and isinstance(schema_def, dict):
            input_schema.json_schema = schema_def
            self._extract_input_fields_from_json_schema(schema_def, input_schema)
            return

        # NEW: Infer from context_scope if no explicit schema
        # This is the new style where input structure is defined by context_scope
        self._infer_tool_input_from_context_scope(config, input_schema)

    def _infer_tool_input_from_context_scope(
        self,
        config: Dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Infer input schema from context_scope declarations.

        For UDFs without explicit input_type, the input structure is defined by
        context_scope.observe declarations. We parse these references and add them
        as required fields.

        Args:
            config: Action configuration with context_scope
            input_schema: InputSchema to populate
        """
        context_scope = config.get("context_scope", {})
        observe = context_scope.get("observe", [])
        passthrough = context_scope.get("passthrough", [])

        # Combine observe and passthrough as inputs
        all_refs = []
        if isinstance(observe, list):
            all_refs.extend(observe)
        if isinstance(passthrough, list):
            all_refs.extend(passthrough)

        if not all_refs:
            # No context_scope declarations - truly dynamic input
            input_schema.is_dynamic = True
            return

        # Parse field references and add as required fields
        for field_ref in all_refs:
            if not isinstance(field_ref, str):
                continue

            # Handle "dep_name.field_name" or "dep_name.*" or just "dep_name"
            if "." in field_ref:
                parts = field_ref.split(".", 1)
                dep_name = parts[0]
                field_path = parts[1] if len(parts) > 1 else "*"

                if field_path == "*":
                    # Wildcard - mark as required dependency but don't add specific fields
                    input_schema.required_fields.add(f"{dep_name}.*")
                else:
                    # Specific field reference
                    input_schema.required_fields.add(field_ref)
            else:
                # Just dependency name - mark entire dependency as required
                input_schema.required_fields.add(f"{field_ref}.*")

        # Mark that this schema was derived from context_scope
        if input_schema.required_fields:
            input_schema.is_dynamic = False
            input_schema.derived_from_context_scope = True

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

    def _extract_llm_schema(
        self,
        config: Dict[str, Any],
        output: OutputSchema,
        schema_loader: Optional[Any],
    ) -> None:
        """Extract schema from LLM action."""
        # Get schema definition (supports 'schema' and 'schema_name')
        schema_def = config.get("schema")
        schema_name = config.get("schema_name")

        # If no inline schema but has schema_name, try to load external schema
        if not schema_def and schema_name:
            # Use SchemaLoader to get raw YAML with full schema structure preserved
            try:
                loaded = SchemaLoader.load_schema(schema_name, self.schema_dir)
            except FileNotFoundError:
                loaded = None
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
                except Exception:
                    pass  # Schema loading failed - will fall through to schemaless

        if not schema_def:
            # Check json_mode - if enabled, action should have schema
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
            # Schema reference (external file) - use SchemaLoader for raw YAML
            try:
                loaded = SchemaLoader.load_schema(schema_def, self.schema_dir)
            except FileNotFoundError:
                loaded = None
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self._extract_fields_from_json_schema(loaded)
            elif schema_loader:
                # Fall back to schema_loader
                try:
                    loaded = schema_loader.load_schema(schema_def)
                    output.json_schema = loaded
                    output.schema_fields = self._extract_fields_from_json_schema(loaded)
                except Exception:
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
        """Extract schema from tool/UDF action using YAML config."""
        # Resolve schema from YAML config (single source of truth)
        schema_def = config.get("schema")
        schema_name = config.get("schema_name")

        # Named schema reference — load from schema file
        if not schema_def and schema_name:
            try:
                loaded = SchemaLoader.load_schema(schema_name, self.schema_dir)
            except FileNotFoundError:
                loaded = None
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self._extract_fields_from_json_schema(loaded)
                return

        if not schema_def:
            output.is_schemaless = True
            return

        if isinstance(schema_def, str):
            # String reference to schema file
            try:
                loaded = SchemaLoader.load_schema(schema_def, self.schema_dir)
            except FileNotFoundError:
                loaded = None
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self._extract_fields_from_json_schema(loaded)
            else:
                output.is_dynamic = True
        elif isinstance(schema_def, dict):
            output.json_schema = schema_def
            output.schema_fields = self._extract_fields_from_json_schema(schema_def)
        elif isinstance(schema_def, list):
            # List-style unified format: [{id: "name", type: "string"}, ...]
            output.json_schema = {"type": "array", "items": schema_def}
            for item in schema_def:
                if isinstance(item, dict) and "id" in item:
                    output.schema_fields.add(item["id"])
                elif isinstance(item, dict) and "name" in item:
                    output.schema_fields.add(item["name"])
        else:
            output.is_dynamic = True

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
            # Observe can be "field" or "action.field" - extract field name
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

    def _extract_fields_from_json_schema(self, schema: Dict[str, Any]) -> Set[str]:
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

    def _extract_field_name(self, reference: str) -> Optional[str]:
        """Extract field name from a reference.

        Handles formats:
        - 'field' -> 'field'
        - 'action.field' -> 'field'
        - 'action.nested.field' -> 'nested'

        Args:
            reference: Reference string

        Returns:
            Field name or None
        """
        if not reference:
            return None

        if "." in reference:
            # Format: action.field or action.nested.field
            parts = reference.split(".")
            if len(parts) >= 2:
                return parts[1]  # Return first field after action
        else:
            return reference

        return None

    def extract_from_workflow(
        self,
        workflow_config: Dict[str, Any],
        schema_loader: Optional[Any] = None,
    ) -> Dict[str, OutputSchema]:
        """Extract schemas from all actions in a workflow.

        Args:
            workflow_config: Full workflow configuration
            schema_loader: Optional schema loader for external schemas

        Returns:
            Dict mapping action names to their output schemas
        """
        schemas: Dict[str, OutputSchema] = {}

        actions = workflow_config.get("actions", [])
        for action in actions:
            name = action.get("name", "unknown")
            schemas[name] = self.extract_schema(action, schema_loader)

        return schemas
