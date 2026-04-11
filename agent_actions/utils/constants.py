"""Centralized configuration key constants."""

# Default action kind when 'kind' is not specified in action config.
# Corresponds to ActionKind.LLM.value from agent_actions.config.schema.
DEFAULT_ACTION_KIND = "llm"

PROJECT_NAME_KEY = "project_name"
MODEL_VENDOR_KEY = "model_vendor"
MODEL_NAME_KEY = "model_name"
JSON_MODE_KEY = "json_mode"
API_KEY_KEY = "api_key"
PROMPT_KEY = "prompt"
SCHEMA_NAME_KEY = "schema_name"
SCHEMA_KEY = "schema"
STRICT_SCHEMA_KEY = "strict_schema"
ON_SCHEMA_MISMATCH_KEY = "on_schema_mismatch"
CHUNK_CONFIG_KEY = "chunk_config"

# Reserved agent/action names that cannot be used in workflows.
# These names are reserved for built-in functionality and config directives.
RESERVED_AGENT_NAMES = frozenset(
    {"source", "version", "workflow", "seed", "prompt", "schema", "context_scope", "action"}
)

# Dangerous patterns that are blocked in user-provided expressions (guards, WHERE clauses, etc.)
# These patterns indicate potentially dangerous operations that could be exploited.
#
# Matched using word boundaries (\b) so that legitimate identifiers like
# "execution_status", "file_count", "directory_path" are NOT false-positived.
DANGEROUS_PATTERNS = frozenset(
    {
        "__import__",
        "exec",
        "eval",
        "compile",
        "open",
        "file",
        "input",
        "raw_input",
        "reload",
        "vars",
        "globals",
        "locals",
        "dir",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "importlib",
        "subprocess",
        "os.system",
        "sys.modules",
    }
)

# Extended dangerous patterns for UDF expressions (includes dunder access)
DANGEROUS_PATTERNS_UDF = DANGEROUS_PATTERNS | {"__"}


def contains_dangerous_pattern(
    expression: str, patterns: frozenset[str] = DANGEROUS_PATTERNS
) -> str | None:
    """Check if expression contains a dangerous pattern as a whole word.

    Uses word-boundary matching (so "exec" blocks "exec(" but NOT
    "execution_status"). The "__" pattern uses substring matching.

    Returns:
        The matched pattern string, or None if clean.
    """
    import re

    for pattern in patterns:
        if pattern == "__":
            if "__" in expression:
                return "__"
        else:
            if re.search(rf"\b{re.escape(pattern)}\b", expression):
                return pattern
    return None


# Supported schema file extensions (suffix form for filtering, glob form for discovery).
SCHEMA_SUFFIXES = (".yml", ".yaml", ".json")
SCHEMA_FILE_GLOBS = tuple(f"*{s}" for s in SCHEMA_SUFFIXES)


# Special namespaces that are always available without explicit dependency declarations.
# These namespaces provide built-in data (source input, version iteration, workflow metadata, etc.)
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

HITL_FILE_GRANULARITY_ERROR = (
    "HITL actions require FILE granularity. "
    "Record granularity launches a separate approval UI per record. "
    "Set 'granularity: file' or remove the granularity field (HITL defaults to file)."
)

# Canonical output schema for HITL actions.
# Fields match _make_terminal_response() in hitl/server.py.
# Pre-compiled here (rather than calling compile_unified_schema) to avoid
# circular imports at module load time.
HITL_OUTPUT_SCHEMA = {
    "name": "hitl_response",
    "fields": [
        {"id": "hitl_status", "type": "string", "required": True},
        {"id": "user_comment", "type": "string", "required": False},
        {"id": "timestamp", "type": "string", "required": True},
    ],
}

HITL_OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "hitl_status": {"type": "string"},
        "user_comment": {"type": "string"},
        "timestamp": {"type": "string"},
    },
    "required": ["hitl_status", "timestamp"],
    "additionalProperties": False,
}
