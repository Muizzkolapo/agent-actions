# agent_actions/models/schema_change.py  (or wherever this helper lives)

from typing import Tuple, Dict, Any


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def compile_field(field: Dict[str, Any], target_system: str) -> Tuple[str, Dict]:
    """
    Convert a single unified field into the shape required by the target system.
    If custom name-mappings exist for that system, apply them.
    """
    target_field = field.get("mappings", {}).get(target_system.lower(), field["id"])

    # base JSON-Schema skeleton
    prop: Dict[str, Any] = {"type": field["type"]}

    # simple passthrough keywords
    for k in ("title", "description", "pattern", "minItems", "maxItems"):
        if k in field:
            prop[k] = field[k]

    # array item schema support
    if field["type"] == "array" and "items" in field:
        prop["items"] = field["items"]

    # enumerations
    if "enum" in field:
        prop["enum"] = field["enum"]

    # validators (currently only “not” supported)
    if "validators" in field:
        for v in field["validators"]:
            if "not" in v:
                prop["not"] = v["not"]
                if "errorMessage" in v:
                    prop["errorMessage"] = v["errorMessage"]

    return target_field, prop


# --------------------------------------------------------------------------- #
# Main compiler                                                               #
# --------------------------------------------------------------------------- #
def compile_unified_schema(unified: Dict[str, Any], target_system: str) -> Dict[str, Any]:
    """
    Convert a unified YAML/JSON definition into the schema dialect required by
    OpenAI, Anthropic, Gemini, **or Ollama** (new).
    """
    properties: Dict[str, Any] = {}
    required:   list[str]      = []

    for field in unified.get("fields", []):
        key, schema_prop = compile_field(field, target_system)
        properties[key] = schema_prop
        if field.get("required", False):
            required.append(key)

    # ------------------------------------------------------------------ #
    # Dialect-specific wrappers                                           #
    # ------------------------------------------------------------------ #
    target = target_system.lower()

    if target == "openai":
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
        compiled = [{
            "name":        unified.get("name", ""),
            "description": unified.get("description", ""),
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False
            }
        }]

    elif target == "gemini":
        compiled = {
            "name":   unified.get("name", ""),
            "schema": properties           # Gemini takes a flat properties map
        }

    elif target == "ollama":
        # Ollama expects the *pure* JSON-Schema object you pass directly to
        # the `format=` parameter—no extra wrapper keys.
        compiled = {
            "title": unified.get("name", ""),
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False
        }

    else:
        from agent_actions.core.exceptions import ConfigValidationError
        raise ConfigValidationError(
            "target_system",
            f"Unknown target system: {target}",
            context={'target_system': target, 'valid_systems': ['openai', 'anthropic', 'gemini', 'ollama'], 'operation': 'compile_unified_schema'}
        )

    return compiled
