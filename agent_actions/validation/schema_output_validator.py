"""Post-LLM schema output validation against expected response schemas."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from agent_actions.config.schema_field import field_is_required, top_level_required_ids
from agent_actions.errors import SchemaValidationError
from agent_actions.validation.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)

_CONSTRAINT_KEYS = ("minimum", "maximum", "enum")

# Reuse the canonical set of JSON Schema keywords defined in SchemaValidator
# rather than maintaining a separate list.  When an LLM "echoes" the schema
# instead of conforming to it, these are the keys that show up.
_JSON_SCHEMA_META_KEYS: frozenset[str] = frozenset(SchemaValidator.JSON_SCHEMA_RESERVED_KEYWORDS)


@dataclass
class SchemaValidationReport:
    """Report on LLM output schema compliance."""

    action_name: str
    schema_name: str
    is_compliant: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Field analysis
    expected_fields: set[str] = field(default_factory=set)
    actual_fields: set[str] = field(default_factory=set)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)

    # Type analysis
    type_errors: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )  # field: (expected, actual)

    # Validation details
    validation_errors: list[str] = field(default_factory=list)
    namespace_hint: str | None = None

    def format_report(self) -> str:
        """Format a human-readable validation report."""
        status = "VALID" if self.is_compliant else "INVALID"
        lines = [
            f"=== Schema Validation Report for '{self.action_name}' ===",
            f"Schema: {self.schema_name}",
            f"Status: {status}",
            f"Timestamp: {self.timestamp.isoformat()}",
            "",
        ]

        if self.expected_fields:
            lines.append(f"Expected fields: {', '.join(sorted(self.expected_fields))}")
        if self.actual_fields:
            lines.append(f"Actual fields: {', '.join(sorted(self.actual_fields))}")
        lines.append("")

        matched = self.expected_fields & self.actual_fields
        if matched:
            lines.append(f"Matched fields ({len(matched)}): {', '.join(sorted(matched))}")

        if self.missing_required:
            lines.append(
                f"MISSING REQUIRED ({len(self.missing_required)}): {', '.join(self.missing_required)}"
            )

        if self.missing_optional:
            lines.append(
                f"Missing optional ({len(self.missing_optional)}): {', '.join(self.missing_optional)}"
            )

        if self.extra_fields:
            lines.append(f"Extra fields ({len(self.extra_fields)}): {', '.join(self.extra_fields)}")

        if self.type_errors:
            lines.append("")
            lines.append("Type mismatches:")
            for field_name, (expected, actual) in self.type_errors.items():
                lines.append(f"  - {field_name}: expected {expected}, got {actual}")

        if self.validation_errors:
            lines.append("")
            lines.append("Validation errors:")
            for error in self.validation_errors:
                lines.append(f"  - {error}")

        lines.append("")
        lines.append("=" * 50)

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            "action_name": self.action_name,
            "schema_name": self.schema_name,
            "is_compliant": self.is_compliant,
            "timestamp": self.timestamp.isoformat(),
            "expected_fields": list(self.expected_fields),
            "actual_fields": list(self.actual_fields),
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "extra_fields": self.extra_fields,
            "type_errors": {
                k: {"expected": v[0], "actual": v[1]} for k, v in self.type_errors.items()
            },
            "validation_errors": self.validation_errors,
        }


def validate_output_against_schema(
    llm_output: Any,
    schema: dict[str, Any],
    action_name: str,
    strict_mode: bool = False,
) -> SchemaValidationReport:
    """Validate LLM response against expected schema."""
    schema_name = schema.get("name", "unknown")

    # FILE tools return a FileUDFResult envelope (outputs=[{source_index, data}]);
    # validate each record's business data, not the envelope keys, so a healthy
    # tool is not reported as an empty object.
    from agent_actions.utils.udf_management.registry import FileUDFResult

    if isinstance(llm_output, FileUDFResult):
        llm_output = [out["data"] for out in llm_output.outputs]

    # Check for malformed 'properties' before extracting fields
    schema_structure_errors = _check_properties_type(schema)

    expected_fields, required_fields, field_types = _extract_schema_fields(schema)
    actual_fields = _extract_output_fields(llm_output)

    missing_required = [f for f in required_fields if f not in actual_fields]
    missing_optional = [f for f in (expected_fields - required_fields) if f not in actual_fields]
    extra_fields = [f for f in actual_fields if f not in expected_fields]

    type_errors = _check_field_types(llm_output, field_types)

    # An explicit `additionalProperties: true` is the author declaring that
    # undeclared keys are expected; strict_mode must not override it.
    extras_permitted = _additional_properties_allowed(schema)

    is_compliant = len(missing_required) == 0 and len(type_errors) == 0
    if strict_mode and extra_fields and not extras_permitted:
        is_compliant = False
    if schema_structure_errors:
        is_compliant = False

    validation_errors: list[str] = schema_structure_errors

    # --- Schema-echo / empty-object guard ---
    # If the schema declares fields but the output contains NONE of them,
    # the response is unusable (catches both {} and schema-echo payloads).
    declared_fields_present = expected_fields & actual_fields
    if expected_fields and not declared_fields_present:
        is_compliant = False
        # Determine whether this is specifically a schema-echo
        undeclared_actual = actual_fields - expected_fields
        if undeclared_actual and undeclared_actual <= _JSON_SCHEMA_META_KEYS:
            validation_errors.append(
                f"Schema-echo detected: output contains JSON Schema meta-keys "
                f"{sorted(undeclared_actual)} instead of declared fields "
                f"{sorted(expected_fields)}. The model returned the schema "
                f"definition itself rather than conforming data."
            )
        elif not actual_fields:
            validation_errors.append(
                f"Empty object: output has no fields but schema declares {sorted(expected_fields)}"
            )
        else:
            validation_errors.append(
                f"No declared fields found in output. "
                f"Expected at least one of {sorted(expected_fields)}, "
                f"got {sorted(actual_fields)}"
            )

    if missing_required:
        validation_errors.append(f"Missing required fields: {', '.join(missing_required)}")
    if type_errors:
        for field_name, (expected, actual) in type_errors.items():
            validation_errors.append(
                f"Type mismatch for '{field_name}': expected {expected}, got {actual}"
            )
    if strict_mode and extra_fields and not extras_permitted:
        validation_errors.append(
            f"Extra fields not allowed in strict mode: {', '.join(extra_fields)}"
        )

    deep_errors = _deep_validation_errors(llm_output, schema, extra_fields)
    if deep_errors:
        is_compliant = False
        validation_errors.extend(deep_errors)

    # Detect action-namespaced output: extra keys whose values are dicts
    # suggest the UDF is passing through namespaced input instead of
    # unwrapping it via content.get("action_name", {}).get("field").
    namespace_hint: str | None = None
    if missing_required and extra_fields:
        namespaced_keys = _detect_namespaced_keys(llm_output, extra_fields)
        if namespaced_keys:
            namespace_hint = (
                f"Hint: extra keys {namespaced_keys} look like action namespaces. "
                f"Tool UDFs receive observed fields namespaced by action name — "
                f'access them via content.get("{namespaced_keys[0]}", {{}}).get("field").'
            )
            validation_errors.append(namespace_hint)

    return SchemaValidationReport(
        action_name=action_name,
        schema_name=schema_name,
        is_compliant=is_compliant,
        expected_fields=expected_fields,
        actual_fields=actual_fields,
        missing_required=missing_required,
        missing_optional=missing_optional,
        extra_fields=extra_fields,
        type_errors=type_errors,
        validation_errors=validation_errors,
        namespace_hint=namespace_hint,
    )


def _detect_namespaced_keys(llm_output: Any, extra_fields: list[str]) -> list[str]:
    """Return extra field names whose values are dicts (likely action namespaces).

    When a tool UDF passes through namespaced input without unwrapping,
    the output contains keys like "canonicalize_qa" with dict values
    instead of the expected flat fields.
    """
    if isinstance(llm_output, list):
        # Check all items, consistent with _extract_output_fields
        for item in llm_output:
            if isinstance(item, dict):
                found = [k for k in extra_fields if isinstance(item.get(k), dict)]
                if found:
                    return found
        return []
    if not isinstance(llm_output, dict):
        return []
    return [k for k in extra_fields if isinstance(llm_output.get(k), dict)]


def _check_properties_type(schema: dict[str, Any]) -> list[str]:
    """Return structural errors for malformed 'properties' values in a schema."""
    errors: list[str] = []
    if "properties" in schema and not isinstance(schema["properties"], dict):
        actual = type(schema["properties"]).__name__
        errors.append(f"Schema 'properties' must be a dict, got {actual}")
    # Check nested schema wrapper
    if "schema" in schema and isinstance(schema["schema"], dict):
        errors.extend(_check_properties_type(schema["schema"]))
    # Check array items
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        items = schema["items"]
        if "properties" in items and not isinstance(items["properties"], dict):
            actual = type(items["properties"]).__name__
            errors.append(f"Schema items 'properties' must be a dict, got {actual}")
    return errors


def _additional_properties_allowed(schema: dict[str, Any]) -> bool:
    """Whether the schema explicitly permits keys it does not declare.

    Mirrors ``_extract_schema_fields``'s descent precedence, so the flag is read
    at the level the declared fields came from. Reading it anywhere else lets the
    two disagree — e.g. an array schema whose fields come from ``items`` while
    the flag is looked up at the top.
    """
    if schema.get("additionalProperties") is True:
        return True
    # These shapes are terminal for field extraction — do not descend past them.
    if "fields" in schema or "properties" in schema:
        return False
    nested = schema.get("schema")
    if isinstance(nested, dict):
        return _additional_properties_allowed(nested)
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        return _additional_properties_allowed(schema["items"])
    return False


def _extract_schema_fields(schema: dict[str, Any]) -> tuple[set[str], set[str], dict[str, str]]:
    """Return (all_fields, required_fields, field_types) from a schema."""
    all_fields: set[str] = set()
    required_fields: set[str] = set()
    field_types: dict[str, str] = {}

    # Handle unified format with 'fields' array
    if "fields" in schema:
        required_by_default = schema.get("required_by_default", False)
        top_level_required = top_level_required_ids(schema)
        for field_def in schema.get("fields", []):
            field_id = field_def.get("id") or field_def.get("name")
            if field_id:
                all_fields.add(field_id)
                if field_is_required(field_def, required_by_default, top_level_required):
                    required_fields.add(field_id)
                if "type" in field_def:
                    field_types[field_id] = field_def["type"]

    # Handle JSON Schema format with 'properties'
    elif "properties" in schema:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            logger.warning(
                "Schema 'properties' must be a dict, got %s; treating as empty",
                type(properties).__name__,
            )
        else:
            all_fields = set(properties.keys())
            required_fields = set(schema.get("required", []))
            for prop_name, prop_def in properties.items():
                if isinstance(prop_def, dict) and "type" in prop_def:
                    field_types[prop_name] = prop_def["type"]

    # Handle nested schema format (e.g., OpenAI compiled)
    elif "schema" in schema and isinstance(schema["schema"], dict):
        nested_schema = schema["schema"]
        return _extract_schema_fields(nested_schema)

    # Handle array schema with items
    elif schema.get("type") == "array" and "items" in schema:
        items = schema.get("items", {})
        if items.get("type") == "object" and "properties" in items:
            properties = items.get("properties", {})
            if not isinstance(properties, dict):
                logger.warning(
                    "Schema items 'properties' must be a dict, got %s; treating as empty",
                    type(properties).__name__,
                )
            else:
                all_fields = set(properties.keys())
                required_fields = set(items.get("required", []))
                for prop_name, prop_def in properties.items():
                    if isinstance(prop_def, dict) and "type" in prop_def:
                        field_types[prop_name] = prop_def["type"]

    # Handle inline schema: keys are field names, values are type strings
    # e.g. {"optimal_code": "string", "score": "number"}
    elif schema and all(isinstance(v, str) for v in schema.values() if v is not None):
        # Exclude known meta-keys (name, description) that aren't field definitions
        meta = {"name", "description"}
        for k, v in schema.items():
            if k not in meta and isinstance(v, str):
                all_fields.add(k)
                field_types[k] = v

    return all_fields, required_fields, field_types


def _deep_validation_errors(
    llm_output: Any,
    schema: dict[str, Any],
    extra_fields: list[str],
) -> list[str]:
    """Constraint checks the flat pass skips: per-element items, additionalProperties, bounds, enum."""
    errors: list[str] = []

    if schema.get("additionalProperties") is False and extra_fields:
        errors.append(
            f"Extra fields not allowed (additionalProperties: false): {', '.join(extra_fields)}"
        )

    if "fields" in schema:
        for field_def in schema.get("fields", []):
            if not isinstance(field_def, dict):
                continue
            field_id = field_def.get("id") or field_def.get("name")
            if field_id:
                errors.extend(_field_value_errors(llm_output, field_id, field_def))
    elif "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_def in schema["properties"].items():
            if isinstance(prop_def, dict):
                errors.extend(_field_value_errors(llm_output, prop_name, prop_def))
    elif "schema" in schema and isinstance(schema["schema"], dict):
        errors.extend(_deep_validation_errors(llm_output, schema["schema"], extra_fields))
    elif (
        schema.get("type") == "array"
        and isinstance(schema.get("items"), dict)
        and isinstance(llm_output, list)
    ):
        errors.extend(_element_errors(llm_output, schema["items"], field_name=None))

    return errors


def _field_value_errors(llm_output: Any, field_name: str, field_def: dict[str, Any]) -> list[str]:
    """Deep errors for one output field: per-element items validation plus value constraints."""
    if not isinstance(llm_output, dict) or field_name not in llm_output:
        return []
    value = llm_output[field_name]
    if value is None:
        return []

    errors: list[str] = []
    items = field_def.get("items")
    if field_def.get("type") == "array" and isinstance(items, dict) and isinstance(value, list):
        errors.extend(_element_errors(value, items, field_name=field_name))
    errors.extend(_constraint_errors(value, field_name, field_def))
    return errors


def _element_errors(
    elements: list[Any],
    items_schema: dict[str, Any],
    field_name: str | None,
) -> list[str]:
    """Validate each array element against the items sub-schema, naming the element index."""
    location = f"'items' for field '{field_name}'" if field_name else "'items'"
    try:
        jsonschema.Draft202012Validator.check_schema(items_schema)
    except jsonschema.exceptions.SchemaError as e:
        return [f"Invalid {location} sub-schema: {e.message}"]

    validator = jsonschema.Draft202012Validator(items_schema)
    prefix = f"Field '{field_name}' element" if field_name else "Element"
    errors: list[str] = []
    for idx, element in enumerate(elements):
        for message in sorted(err.message for err in validator.iter_errors(element)):
            errors.append(f"{prefix} {idx}: {message}")
    return errors


def _constraint_errors(value: Any, field_name: str, field_def: dict[str, Any]) -> list[str]:
    """Validate a field value against its declared minimum/maximum/enum constraints."""
    constraints = {k: field_def[k] for k in _CONSTRAINT_KEYS if k in field_def}
    if not constraints:
        return []
    try:
        jsonschema.Draft202012Validator.check_schema(constraints)
    except jsonschema.exceptions.SchemaError as e:
        return [f"Invalid constraints for field '{field_name}': {e.message}"]

    validator = jsonschema.Draft202012Validator(constraints)
    return [
        f"Field '{field_name}': {message}"
        for message in sorted(err.message for err in validator.iter_errors(value))
    ]


def _extract_output_fields(llm_output: Any) -> set[str]:
    """Extract field names from LLM output."""
    if isinstance(llm_output, dict):
        return set(llm_output.keys())
    elif isinstance(llm_output, list) and llm_output:
        # For array output, extract fields from all items
        all_keys: set[str] = set()
        for item in llm_output:
            if isinstance(item, dict):
                all_keys.update(item.keys())
        return all_keys
    return set()


def _check_field_types(
    llm_output: Any,
    field_types: dict[str, str],
) -> dict[str, tuple[str, str]]:
    """Return field-to-(expected, actual) mapping for type mismatches."""
    type_errors: dict[str, tuple[str, str]] = {}

    if not isinstance(llm_output, dict):
        return type_errors

    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for field_name, expected_type in field_types.items():
        if field_name not in llm_output:
            continue

        value = llm_output[field_name]
        if value is None:
            continue  # None is typically allowed for optional fields

        expected_python_type = type_map.get(expected_type)
        if expected_python_type is None:
            continue

        # Python's bool is a subclass of int, so isinstance(True, int)
        # returns True.  Reject booleans for integer/number checks.
        if isinstance(value, bool) and expected_type in ("integer", "number"):
            type_errors[field_name] = (expected_type, "bool")
        elif not isinstance(value, expected_python_type):  # type: ignore[arg-type]
            actual_type = type(value).__name__
            type_errors[field_name] = (expected_type, actual_type)

    return type_errors


def validate_and_raise_if_invalid(
    llm_output: Any,
    schema: dict[str, Any],
    action_name: str,
    strict_mode: bool = False,
) -> SchemaValidationReport:
    """Validate LLM output and raise SchemaValidationError if invalid.

    Raises:
        SchemaValidationError: If validation fails.
    """
    report = validate_output_against_schema(llm_output, schema, action_name, strict_mode)

    if not report.is_compliant:
        hint = "Check that the LLM prompt clearly specifies the expected output format"
        if report.namespace_hint:
            hint = f"{hint}. {report.namespace_hint}"
        raise SchemaValidationError(
            f"LLM output does not match expected schema for action '{action_name}'",
            schema_name=report.schema_name,
            validation_type="output",
            action_name=action_name,
            expected_fields=list(report.expected_fields),
            actual_fields=list(report.actual_fields),
            missing_fields=report.missing_required,
            extra_fields=report.extra_fields,
            type_errors=report.type_errors,
            hint=hint,
        )

    return report
