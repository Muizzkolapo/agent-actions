"""Configuration for reprompting system with preset support.

Simple usage:
    reprompt: true        # Basic preset
    reprompt: smart       # LLM critique on 3rd+ attempt
    reprompt: thorough    # Full pipeline with self-reflection

Advanced usage:
    reprompt:
        preset: smart
        max_attempts: 5
        json_repair: true
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# Preset definitions
PRESETS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "max_attempts": 3,
        "json_repair": True,
        "use_llm_critique": False,
        "use_self_reflection": False,
        "critique_after_attempt": 999,  # Never (basic doesn't use critique)
    },
    "smart": {
        "max_attempts": 4,
        "json_repair": True,
        "use_llm_critique": True,
        "use_self_reflection": False,
        "critique_after_attempt": 2,  # Use critique starting on 3rd attempt
    },
    "thorough": {
        "max_attempts": 5,
        "json_repair": True,
        "use_llm_critique": True,
        "use_self_reflection": True,
        "critique_after_attempt": 1,  # Use critique starting on 2nd attempt
    },
}


@dataclass
class RepromptConfig:
    """Simple configuration for reprompting with preset support.

    Attributes:
        enabled: Whether reprompting is enabled
        preset: One of 'basic', 'smart', 'thorough'
        max_attempts: Maximum retry attempts
        json_repair: Whether to attempt JSON repair before reprompting
        use_llm_critique: Whether to use LLM to analyze failures
        use_self_reflection: Whether to include model self-reflection
        critique_after_attempt: Attempt number after which to use critique
        constraints: List of constraint configurations
    """

    enabled: bool = True
    preset: str = "basic"
    max_attempts: int = 3
    json_repair: bool = True
    use_llm_critique: bool = False
    use_self_reflection: bool = False
    critique_after_attempt: int = 2
    constraints: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Apply preset defaults if not explicitly overridden."""
        if self.preset in PRESETS:
            preset_values = PRESETS[self.preset]
            # Only apply preset values for fields that weren't explicitly set
            # This is handled in from_yaml() where we track explicit overrides

    @classmethod
    def from_yaml(cls, value: Union[bool, str, Dict[str, Any], None]) -> "RepromptConfig":
        """Parse reprompt config from YAML value.

        Supports three forms:
        1. Boolean: reprompt: true (uses basic preset)
        2. String: reprompt: smart (uses named preset)
        3. Dict: reprompt: {preset: smart, max_attempts: 5}

        Args:
            value: The YAML value for reprompt config

        Returns:
            RepromptConfig instance

        Examples:
            >>> RepromptConfig.from_yaml(True)
            RepromptConfig(enabled=True, preset='basic', ...)

            >>> RepromptConfig.from_yaml('smart')
            RepromptConfig(enabled=True, preset='smart', ...)

            >>> RepromptConfig.from_yaml({'preset': 'thorough', 'max_attempts': 7})
            RepromptConfig(enabled=True, preset='thorough', max_attempts=7, ...)
        """
        # Handle None or False - disabled
        if value is None or value is False:
            return cls(enabled=False)

        # Handle True - use basic preset
        if value is True:
            preset_values = PRESETS["basic"]
            return cls(
                enabled=True,
                preset="basic",
                max_attempts=preset_values["max_attempts"],
                json_repair=preset_values["json_repair"],
                use_llm_critique=preset_values["use_llm_critique"],
                use_self_reflection=preset_values["use_self_reflection"],
                critique_after_attempt=preset_values["critique_after_attempt"],
            )

        # Handle string preset name
        if isinstance(value, str):
            preset_name = value.lower()
            if preset_name not in PRESETS:
                valid_presets = ", ".join(PRESETS.keys())
                raise ValueError(
                    f"Unknown reprompt preset '{preset_name}'. "
                    f"Valid presets: {valid_presets}"
                )
            preset_values = PRESETS[preset_name]
            return cls(
                enabled=True,
                preset=preset_name,
                max_attempts=preset_values["max_attempts"],
                json_repair=preset_values["json_repair"],
                use_llm_critique=preset_values["use_llm_critique"],
                use_self_reflection=preset_values["use_self_reflection"],
                critique_after_attempt=preset_values["critique_after_attempt"],
            )

        # Handle dict config
        if isinstance(value, dict):
            # Get preset (default to basic)
            preset_name = value.get("preset", "basic")
            if isinstance(preset_name, str):
                preset_name = preset_name.lower()
            if preset_name not in PRESETS:
                valid_presets = ", ".join(PRESETS.keys())
                raise ValueError(
                    f"Unknown reprompt preset '{preset_name}'. "
                    f"Valid presets: {valid_presets}"
                )

            # Start with preset defaults
            preset_values = PRESETS[preset_name]

            # Override with explicit values from config
            return cls(
                enabled=value.get("enabled", True),
                preset=preset_name,
                max_attempts=value.get("max_attempts", preset_values["max_attempts"]),
                json_repair=value.get("json_repair", preset_values["json_repair"]),
                use_llm_critique=value.get(
                    "use_llm_critique", preset_values["use_llm_critique"]
                ),
                use_self_reflection=value.get(
                    "use_self_reflection", preset_values["use_self_reflection"]
                ),
                critique_after_attempt=value.get(
                    "critique_after_attempt", preset_values["critique_after_attempt"]
                ),
                constraints=value.get("constraints", []),
            )

        raise ValueError(
            f"Invalid reprompt config type: {type(value).__name__}. "
            "Expected bool, str, or dict."
        )

    def should_use_critique(self, attempt: int) -> bool:
        """Check if LLM critique should be used for this attempt.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            True if critique should be used
        """
        return self.use_llm_critique and attempt >= self.critique_after_attempt

    def should_use_reflection(self, attempt: int) -> bool:
        """Check if self-reflection should be used for this attempt.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            True if self-reflection should be used
        """
        return self.use_self_reflection and attempt >= self.critique_after_attempt
