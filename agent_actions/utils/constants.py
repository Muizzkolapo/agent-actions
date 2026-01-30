"""Centralized configuration key constants."""

MODEL_VENDOR_KEY = "model_vendor"
MODEL_NAME_KEY = "model_name"
JSON_MODE_KEY = "json_mode"
API_KEY_KEY = "api_key"
PROMPT_KEY = "prompt"
SCHEMA_NAME_KEY = "schema_name"
SCHEMA_KEY = "schema"
STRICT_SCHEMA_KEY = "strict_schema"
CHUNK_CONFIG_KEY = "chunk_config"

# Reserved agent/action names that cannot be used in workflows.
# These names are reserved for built-in functionality and config directives.
RESERVED_AGENT_NAMES = frozenset(
    {"source", "loop", "workflow", "seed", "prompt", "schema", "context_scope", "action"}
)

# Special namespaces that are always available without explicit dependency declarations.
# These namespaces provide built-in data (source input, loop iteration, workflow metadata, etc.)
# and don't require being listed in an action's "dependencies" field.
#
# Relationship to RESERVED_AGENT_NAMES:
# - SPECIAL_NAMESPACES is a subset of RESERVED_AGENT_NAMES
# - "context_scope" is reserved (can't be an action name) but is NOT a runtime namespace
#   (it's a config directive, not a data source you can reference in templates)
#
# Used by:
# - Static analyzers (data_flow_graph, reference_extractor, type_checker)
# - Field resolution validators
# - Context scope processor
SPECIAL_NAMESPACES = RESERVED_AGENT_NAMES - {"context_scope"}
