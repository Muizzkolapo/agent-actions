"""
Centralized config field definitions for ActionExpander.
"""

import copy
from typing import Dict, Any

# Simple config fields that follow standard inheritance pattern
# Format: 'field_name': default_value
#
# None = required field (no default)
# True/False = boolean defaults
# 0 = numeric defaults
# 'string' = string defaults
SIMPLE_CONFIG_FIELDS = {
    # Required model configuration (no defaults - must be provided)
    "model_vendor": None,
    "model_name": None,
    "api_key": None,
    "base_url": None,  # Optional: base URL for vendors like Ollama
    # Action type
    "kind": "llm",  # Default: 'llm' (LLM action). Use 'tool' for UDF actions.
    # Execution settings
    "run_mode": "online",  # Default: online mode
    "granularity": "record",  # Default: record-level processing. Use 'file' for batch processing (tool only).
    "is_operational": True,  # Default: enabled
    # LLM configuration
    "json_mode": True,  # Default: True (JSON-based system)
    "prompt_debug": False,  # Default: False (no debug output)
    "output_field": "raw_response",  # Default: 'raw_response' (for non-JSON vendors like Ollama)
    # Generation parameters (provider-agnostic; mapped to vendor-specific keys in each client)
    "temperature": None,  # Default: None (use provider default)
    "max_tokens": None,  # Default: None (use provider default)
    "top_p": None,  # Default: None (use provider default)
    "stop": None,  # Default: None (no stop sequences)
    # Reprompt configuration
    "reprompt": False,  # Default: False (reprompting disabled)
    "constraints": (),  # Default: empty tuple (immutable — no cross-agent mutation)
    # Retry configuration (transport-layer failure handling)
    "retry": None,  # Default: None (retry disabled unless configured)
    # Runtime-consumed fields (providers and managers read these from agent dict)
    "ephemeral": None,
    "anthropic_version": None,
    "enable_prompt_caching": None,
    "max_execution_time": None,
    "where_clause": None,
    "enable_caching": None,
}


def inherit_simple_fields(
    agent: Dict[str, Any], action: Dict[str, Any], defaults: Dict[str, Any]
) -> None:
    """
    Automatically inherit simple config fields from action/defaults.

    Inheritance priority:
        1. Action-level value (highest priority)
        2. Defaults-level value
        3. Hardcoded default from SIMPLE_CONFIG_FIELDS (lowest priority)

    Args:
        agent: Agent config dict to populate (modified in-place)
        action: Action config from YAML
        defaults: Default config from YAML

    Example:
        action = {'model_vendor': 'anthropic', 'json_mode': True}
        defaults = {'model_vendor': 'openai', 'model_name': 'gpt-4'}
        agent = {}

        inherit_simple_fields(agent, action, defaults)

        Result:
            agent = {
                'model_vendor': 'anthropic',  # From action (overrides defaults)
                'model_name': 'gpt-4',        # From defaults (not in action)
                'api_key': None,              # From hardcoded default
                'run_mode': 'online',         # From hardcoded default
                'is_operational': True,       # From hardcoded default
                'json_mode': True,            # From action (overrides default)
                'prompt_debug': False,        # From hardcoded default
            }
    """
    for field, default_value in SIMPLE_CONFIG_FIELDS.items():
        # Standard inheritance: action > defaults > hardcoded default
        value = action.get(field, defaults.get(field, default_value))
        # Normalize run_mode to lowercase for case-insensitive comparison
        if field == "run_mode" and isinstance(value, str):
            value = value.lower()
        # Deep-copy mutable values to prevent cross-agent state leakage
        if isinstance(value, (list, dict)):
            value = copy.deepcopy(value)
        agent[field] = value


__all__ = ["SIMPLE_CONFIG_FIELDS", "inherit_simple_fields"]
