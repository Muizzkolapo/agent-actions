"""Extract output schemas from action configurations."""

import logging
from pathlib import Path
from typing import Any

from agent_actions.config.path_config import get_tool_dirs, resolve_project_root
from agent_actions.errors import ConfigValidationError
from agent_actions.output.response.config_fields import get_default
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.tooling.code_scanner import scan_tool_functions
from agent_actions.utils.constants import DEFAULT_ACTION_KIND, HITL_OUTPUT_JSON_SCHEMA

from .data_flow_graph import InputSchema, OutputSchema

logger = logging.getLogger(__name__)


class SchemaExtractor:
    """Extracts output schemas from LLM, tool, and HITL action types."""

    def __init__(
        self,
        udf_registry: dict[str, Any] | None = None,
        project_root: Path | None = None,
        tool_schemas: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the schema extractor.

        Args:
            tool_schemas: Pre-scanned tool function schemas. When provided,
                skips the per-instance ``scan_tool_functions`` call.
        """
        self.udf_registry = udf_registry or {}
        self.project_root = resolve_project_root(project_root)
        self._tool_schemas: dict[str, Any] | None = tool_schemas

    def _load_schema_by_name(self, schema_name: str) -> dict:
        """Load a schema by name using multi-level resolution."""
        return SchemaLoader.load_schema(
            schema_name,
            project_root=self.project_root,
        )

    def _get_tool_schemas(self) -> dict[str, Any]:
        """Lazy-load tool schemas from Python files."""
        if self._tool_schemas is None:
            tool_paths = get_tool_dirs(self.project_root)
            self._tool_schemas = scan_tool_functions(self.project_root, tool_paths)
        return self._tool_schemas

    def _convert_fields_to_json_schema(self, fields: list[dict[str, str]]) -> dict[str, Any]:
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

    def _mark_schema_load_failure(
        self, output: OutputSchema, schema_id: str, error: Exception | None = None
    ) -> None:
        """Mark output as dynamic due to a schema loading failure."""
        output.is_dynamic = True
        if error:
            output.load_error = f"Schema '{schema_id}' could not be loaded: {error}"
        else:
            output.load_error = f"Schema '{schema_id}' not found in {self.project_root}"

    def _try_load_schema(
        self,
        output: OutputSchema,
        schema_id: str,
        schema_loader: Any | None,
    ) -> bool:
        """Try to load a schema by name, returning True on success.

        Resolution order: SchemaLoader.load_schema (file-based) first,
        then fallback to injected schema_loader. Marks failure on output
        if neither succeeds.
        """
        # Try file-based loader first
        try:
            loaded = self._load_schema_by_name(schema_id)
        except (FileNotFoundError, ConfigValidationError):
            loaded = None
        if loaded:
            output.json_schema = loaded
            output.schema_fields = self.extract_fields_from_json_schema(loaded)
            return True

        # Try injected loader as fallback
        if schema_loader:
            try:
                loaded = schema_loader.load_schema(schema_id)
                output.json_schema = loaded
                output.schema_fields = self.extract_fields_from_json_schema(loaded)  # type: ignore[arg-type]
                return True
            except (FileNotFoundError, KeyError, ValueError, OSError) as e:
                logger.warning("Schema loading failed for '%s': %s", schema_id, e, exc_info=True)
                self._mark_schema_load_failure(output, schema_id, e)
                return False

        # Neither loader found it
        self._mark_schema_load_failure(output, schema_id)
        return False

    def extract_schema(
        self,
        agent_config: dict[str, Any],
        schema_loader: Any | None = None,
    ) -> OutputSchema:
        """Extract output schema from action config."""
        output = OutputSchema()

        kind = agent_config.get("kind", DEFAULT_ACTION_KIND)
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_schema(agent_config, output)
        elif kind == "hitl" or model_vendor == "hitl":
            self._extract_hitl_schema(output)
        else:
            self._extract_llm_schema(agent_config, output, schema_loader)

        self._apply_context_scope(agent_config, output)

        return output

    def extract_input_schema(
        self,
        agent_config: dict[str, Any],
        reference_extractor: Any | None = None,
    ) -> InputSchema:
        """Extract input schema from action config."""
        input_schema = InputSchema()

        kind = agent_config.get("kind", DEFAULT_ACTION_KIND)
        model_vendor = agent_config.get("model_vendor", "")

        if kind == "tool" or model_vendor == "tool":
            self._extract_tool_input_schema(agent_config, input_schema)
        elif kind == "hitl" or model_vendor == "hitl":
            pass
        else:
            self._extract_llm_input_schema(agent_config, input_schema, reference_extractor)

        return input_schema

    def _extract_llm_input_schema(
        self,
        config: dict[str, Any],
        input_schema: InputSchema,
        reference_extractor: Any | None = None,
    ) -> None:
        """Extract input schema from LLM action config."""
        if reference_extractor is None:
            from .reference_extractor import (
                ReferenceExtractor,
            )

            reference_extractor = ReferenceExtractor()

        requirements = reference_extractor.extract_from_agent(config)

        for req in requirements:
            if req.source_agent and req.field_path:
                field_ref = f"{req.source_agent}.{req.field_path}"
            else:
                field_ref = req.field_path or ""

            if field_ref:
                input_schema.required_fields.add(field_ref)

    def _extract_tool_input_schema(
        self,
        config: dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Extract input schema from tool/UDF action."""
        impl = config.get("impl") or config.get("model_name") or ""

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

        impl_key = impl.lower() if impl else ""
        if impl_key and impl_key in self.udf_registry:
            udf_info = self.udf_registry[impl_key]
            json_schema = udf_info.get("json_schema")  # Input schema (may be None for new style)
            if json_schema:
                input_schema.json_schema = json_schema
                self._extract_input_fields_from_json_schema(json_schema, input_schema)
                return

        schema_def = config.get("input_schema")
        if schema_def and isinstance(schema_def, dict):
            input_schema.json_schema = schema_def
            self._extract_input_fields_from_json_schema(schema_def, input_schema)
            return

        self._infer_tool_input_from_context_scope(config, input_schema)

    def _infer_tool_input_from_context_scope(
        self,
        config: dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Infer input schema from context_scope declarations."""
        context_scope = config.get("context_scope", {})
        observe = context_scope.get("observe", [])
        passthrough = context_scope.get("passthrough", [])

        all_refs = []
        if isinstance(observe, list):
            all_refs.extend(observe)
        if isinstance(passthrough, list):
            all_refs.extend(passthrough)

        if not all_refs:
            input_schema.is_dynamic = True
            return

        for field_ref in all_refs:
            if not isinstance(field_ref, str):
                continue

            if "." in field_ref:
                parts = field_ref.split(".", 1)
                dep_name = parts[0]
                field_path = parts[1] if len(parts) > 1 else "*"

                if field_path == "*":
                    input_schema.required_fields.add(f"{dep_name}.*")
                else:
                    input_schema.required_fields.add(field_ref)
            else:
                input_schema.required_fields.add(f"{field_ref}.*")

        if input_schema.required_fields:
            input_schema.is_dynamic = False
            input_schema.derived_from_context_scope = True

    def _extract_input_fields_from_json_schema(
        self,
        schema: dict[str, Any],
        input_schema: InputSchema,
    ) -> None:
        """Extract required and optional fields from JSON schema."""
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        for field_name in properties.keys():
            if field_name in required:
                input_schema.required_fields.add(field_name)
            else:
                input_schema.optional_fields.add(field_name)

    def _extract_llm_schema(
        self,
        config: dict[str, Any],
        output: OutputSchema,
        schema_loader: Any | None,
    ) -> None:
        """Extract schema from LLM action."""
        schema_def = config.get("schema") or config.get("output_schema")
        schema_name = config.get("schema_name")

        if not schema_def and schema_name:
            self._try_load_schema(output, schema_name, schema_loader)
            return

        if not schema_def:
            json_mode = config.get("json_mode", get_default("json_mode"))
            if not json_mode:
                output.is_schemaless = True
                output_field = config.get("output_field", get_default("output_field"))
                output.schema_fields.add(output_field)
                output.schema_fields.add("content")
                return

            output.is_schemaless = True
            output.schema_fields.add("content")
            return

        if isinstance(schema_def, str):
            self._try_load_schema(output, schema_def, schema_loader)
        elif isinstance(schema_def, dict):
            output.json_schema = schema_def
            output.schema_fields = self.extract_fields_from_json_schema(schema_def)
        elif isinstance(schema_def, list):
            output.json_schema = {"type": "array", "items": schema_def}
            for item in schema_def:
                if isinstance(item, dict) and "id" in item:
                    output.schema_fields.add(item["id"])
                elif isinstance(item, dict) and "name" in item:
                    output.schema_fields.add(item["name"])

    def _extract_tool_schema(
        self,
        config: dict[str, Any],
        output: OutputSchema,
    ) -> None:
        """Extract schema from tool/UDF action using YAML config."""
        schema_def = config.get("schema") or config.get("output_schema")
        schema_name = config.get("schema_name")

        if not schema_def and schema_name:
            try:
                loaded = self._load_schema_by_name(schema_name)
            except FileNotFoundError:
                loaded = None
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self.extract_fields_from_json_schema(loaded)
                return

        if not schema_def:
            output.is_schemaless = True
            return

        if isinstance(schema_def, str):
            try:
                loaded = self._load_schema_by_name(schema_def)
            except FileNotFoundError:
                loaded = None
            if loaded:
                output.json_schema = loaded
                output.schema_fields = self.extract_fields_from_json_schema(loaded)
            else:
                output.is_dynamic = True
        elif isinstance(schema_def, dict):
            output.json_schema = schema_def
            output.schema_fields = self.extract_fields_from_json_schema(schema_def)
        elif isinstance(schema_def, list):
            output.json_schema = {"type": "array", "items": schema_def}
            for item in schema_def:
                if isinstance(item, dict) and "id" in item:
                    output.schema_fields.add(item["id"])
                elif isinstance(item, dict) and "name" in item:
                    output.schema_fields.add(item["name"])
        else:
            output.is_dynamic = True

    def _extract_hitl_schema(self, output: OutputSchema) -> None:
        """Extract schema for HITL actions using the canonical HITL output schema.

        Always applies the canonical schema regardless of any inline schema
        on the action config — the HITL runtime contract is fixed.
        """
        output.json_schema = HITL_OUTPUT_JSON_SCHEMA
        output.schema_fields = self.extract_fields_from_json_schema(HITL_OUTPUT_JSON_SCHEMA)

    def _apply_context_scope(self, config: dict[str, Any], output: OutputSchema) -> None:
        """Apply context_scope directives to output schema."""
        observe = config.get("observe", [])
        for ref in observe:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.observe_fields.add(field_name)

        drops = config.get("drops", [])
        for ref in drops:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.dropped_fields.add(field_name)

        context_scope = config.get("context_scope", {})

        passthrough = context_scope.get("passthrough", [])
        for ref in passthrough:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.passthrough_fields.add(field_name)

        scope_observe = context_scope.get("observe", [])
        for ref in scope_observe:
            field_name = self._extract_field_name(ref)
            if field_name:
                output.observe_fields.add(field_name)

        scope_drops = context_scope.get("drop")
        for ref in scope_drops or []:  # or [] guards against explicit null (drop: null in config)
            field_name = self._extract_field_name(ref)
            if field_name:
                output.dropped_fields.add(field_name)

        if config.get("return_collection"):
            output.schema_fields.add("input_data")

    def extract_fields_from_json_schema(self, schema: dict[str, Any]) -> set[str]:
        """Extract top-level field names from JSON schema."""
        fields: set[str] = set()

        schema_type = schema.get("type", "object")

        if schema_type == "object":
            properties = schema.get("properties", {})
            fields.update(properties.keys())
        elif schema_type == "array":
            name = schema.get("name", "items")
            fields.add(name)

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
                if isinstance(value, str):
                    fields.add(key)
                elif isinstance(value, dict):
                    if "type" in value or any(k in value for k in ["properties", "items"]):
                        fields.add(key)

        if "fields" in schema:
            for field_def in schema["fields"]:
                if isinstance(field_def, dict):
                    field_id = field_def.get("id") or field_def.get("name")
                    if field_id:
                        fields.add(field_id)

        if schema_type == "array" and "items" in schema:
            items = schema["items"]
            if isinstance(items, dict) and "properties" in items:
                fields.update(items["properties"].keys())

        return fields

    def _extract_field_name(self, reference: str) -> str | None:
        """Extract field name from a reference string."""
        if not reference:
            return None
        if "." not in reference:
            return reference
        parts = reference.split(".", 1)
        field = parts[1] if parts[1] else None  # None for malformed like "ns."
        # "*" is a wildcard directive (observe all), not a literal field name.
        # Returning None prevents it from entering observe/passthrough field sets.
        if field == "*":
            return None
        return field

    def extract_from_workflow(
        self,
        workflow_config: dict[str, Any],
        schema_loader: Any | None = None,
    ) -> dict[str, OutputSchema]:
        """Extract schemas from all actions in a workflow."""
        schemas: dict[str, OutputSchema] = {}

        actions = workflow_config.get("actions", [])
        for action in actions:
            name = action.get("name", "unknown")
            schemas[name] = self.extract_schema(action, schema_loader)

        return schemas
