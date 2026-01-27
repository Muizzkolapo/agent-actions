"""Centralized configuration key constants."""

MODEL_VENDOR_KEY = "model_vendor"
MODEL_NAME_KEY = "model_name"
JSON_MODE_KEY = "json_mode"
API_KEY_KEY = "api_key"
PROMPT_KEY = "prompt"
SCHEMA_NAME_KEY = "schema_name"
SCHEMA_KEY = "schema"
CHUNK_CONFIG_KEY = "chunk_config"

# Reserved agent/action names that cannot be used in workflows.
RESERVED_AGENT_NAMES = frozenset(
    {"source", "loop", "workflow", "seed", "prompt", "schema", "context_scope", "action"}
)

# Special namespaces that are always available without explicit dependency declarations.
# These namespaces provide built-in data (source input, loop iteration, workflow metadata, etc.)
# and don't require being listed in an action's "dependencies" field.
#
# Used by:
# - Static analyzers (data_flow_graph, reference_extractor, type_checker)
# - Field resolution validators
# - Context scope processor
#
# Note: This is a superset used for validation. Individual components may check
# subsets based on their specific context (e.g., scope.py only uses source/loop/workflow).
SPECIAL_NAMESPACES = frozenset(
    {"source", "loop", "workflow", "seed", "prompt", "schema", "action"}
)
