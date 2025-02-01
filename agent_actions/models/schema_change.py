import yaml
import json
import sys

def compile_field(field, target_system):
    """
    Dynamically compile a single field definition.
    If the field contains a mapping for the target system,
    use it; otherwise, use the original field id.
    """
    # Check for target-specific mapping if provided.
    target_field = field.get("mappings", {}).get(target_system.lower(), field["id"])
    
    # Start with the basic type.
    prop = {"type": field["type"]}
    
    # Include additional JSON Schema keywords if provided.
    for keyword in ["title", "description", "pattern", "minItems", "maxItems"]:
        if keyword in field:
            prop[keyword] = field[keyword]
    
    # For array type fields, include the items schema if provided.
    if field["type"] == "array" and "items" in field:
        prop["items"] = field["items"]
    
    # Add enum if provided.
    if "enum" in field:
        prop["enum"] = field["enum"]
    
    # Add validators if provided.
    if "validators" in field:
        for validator in field["validators"]:
            if "not" in validator:
                prop["not"] = validator["not"]
                # Optionally, include the error message.
                if "errorMessage" in validator:
                    prop["errorMessage"] = validator["errorMessage"]
    
    return target_field, prop

def compile_unified_schema(unified, target_system):
    """
    Dynamically compile the unified schema into the target system schema.
    The function uses the user's file definitions (including any custom mappings)
    to build the appropriate JSON schema.
    """
    properties = {}
    required = []

    for field in unified.get("fields", []):
        target_field, prop = compile_field(field, target_system)
        properties[target_field] = prop
        if field.get("required", False):
            required.append(target_field)

    # Build the final schema differently based on target.
    target = target_system.lower()
    if target == "openai":
        # For OpenAI, we assume the schema is embedded in a "schema" key.
        compiled = {
            "name": unified.get("name", ""),
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False
            }
        }
    elif target == "anthropic":
        # For Anthropic, assume the schema is under "input_schema" and returned in a list.
        compiled = [{
            "name": unified.get("name", ""),
            "description": unified.get("description", ""),
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False
            }
        }]
    elif target == "gemini":
        # For Gemini, we assume that the schema is a direct mapping of the properties.
        # This allows Gemini to receive fields with extra keywords (like title, description, etc.)
        compiled = {
            "name": unified.get("name", ""),
            "schema": properties
        }
    else:
        raise ValueError("Unknown target system. Choose either 'openai', 'anthropic', or 'gemini'.")
    
    return compiled
