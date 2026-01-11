"""
Centralized config field definitions for ActionExpander.
"""

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
    # Execution settings
    "run_mode": "online",  # Default: online mode
    "is_operational": True,  # Default: enabled
    # LLM configuration
    "json_mode": True,  # Default: True (JSON-based system)
    "prompt_debug": False,  # Default: False (no debug output)
    "few_shot": 0,  # Default: 0 (no few-shot examples)
    "output_field": "raw_response",  # Default: 'raw_response' (for non-JSON vendors like Ollama)
    # Tool configuration
    "side_output": False,  # Default: False (tool-specific conditional output)
    # Reprompt configuration
    "reprompt": False,  # Default: False (reprompting disabled)
    "constraints": [],  # Default: empty list (no constraints)
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
                'few_shot': 0                 # From hardcoded default
            }
    """
    for field, default_value in SIMPLE_CONFIG_FIELDS.items():
        # Standard inheritance: action > defaults > hardcoded default
        agent[field] = action.get(field, defaults.get(field, default_value))


__all__ = ["SIMPLE_CONFIG_FIELDS", "inherit_simple_fields"]
