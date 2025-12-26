"""Reprompting system for improving LLM outputs through iterative refinement.

This package provides:
- RepromptConfig: Simple configuration with presets (basic, smart, thorough)
- ConstraintValidator: Built-in constraint validation
- JSONRepairStrategy: JSON repair before reprompting
- RepromptEngine: Core reprompt logic
- RepromptInterceptor: Integration with interceptor system

Simple usage in workflow YAML:
    reprompt: true  # Uses 'basic' preset with sensible defaults
    reprompt: smart  # Uses LLM critique on 3rd+ attempt
    reprompt: thorough  # Full pipeline with self-reflection
"""

from agent_actions.reprompting.config import RepromptConfig
from agent_actions.reprompting.constraints import ConstraintValidator
from agent_actions.reprompting.json_repair import JSONRepairStrategy
from agent_actions.reprompting.engine import RepromptEngine, RepromptResult

__all__ = [
    "RepromptConfig",
    "ConstraintValidator",
    "JSONRepairStrategy",
    "RepromptEngine",
    "RepromptResult",
]
