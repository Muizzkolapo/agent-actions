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
