"""Consolidated guard configuration with explicit behavior control."""

from enum import Enum
from typing import Union, Dict, Any
from .guard_parser import GuardParser, GuardType


class GuardBehavior(str, Enum):
    """Behavior options when guard condition fails."""
    SKIP = "skip"        # Agent doesn't process, records pass through (passthrough)
    FILTER = "filter"    # Records are removed entirely from pipeline
    WRITE_TO = "write_to"    # Future: Write failed records to specified location
    REPROCESS = "reprocess"  # Future: Send to different agent/action


class GuardConfig:
    """Consolidated guard configuration with condition and behavior control."""

    def __init__(self, condition: str, on_false: Union[GuardBehavior, str]):
        """
        Initialize guard configuration.

        Args:
            condition: Guard expression (SQL or UDF format)
            on_false: Behavior when condition fails
        """
        self.condition = condition
        self.on_false = GuardBehavior(on_false) if isinstance(on_false, str) else on_false

        # Validate the condition using existing GuardParser
        self._parsed_condition = GuardParser.parse(condition)

    def is_udf_condition(self) -> bool:
        """Check if condition is a UDF expression."""
        return self._parsed_condition.type == GuardType.UDF

    def is_sql_condition(self) -> bool:
        """Check if condition is a SQL-like expression."""
        return self._parsed_condition.type == GuardType.SQL

    def get_condition_expression(self) -> str:
        """Get the clean condition expression (without udf: prefix)."""
        return self._parsed_condition.expression

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'GuardConfig':
        """
        Create GuardConfig from dictionary (YAML format).

        Args:
            config_dict: Dictionary with 'condition' and 'on_false' keys

        Returns:
            GuardConfig instance

        Raises:
            ValueError: If required keys are missing
        """
        if not isinstance(config_dict, dict):
            raise ValueError("Guard config must be a dictionary")

        if 'condition' not in config_dict:
            raise ValueError("Guard dict must have 'condition' key")

        condition = config_dict['condition']
        on_false = config_dict.get('on_false', 'filter')  # Default to filter

        return cls(condition=condition, on_false=on_false)

    @classmethod
    def from_string(cls, guard_string: str) -> 'GuardConfig':
        """
        Create GuardConfig from legacy string format.

        Args:
            guard_string: Legacy guard expression string

        Returns:
            GuardConfig with appropriate default behavior
        """
        # Parse to determine type and set appropriate default behavior
        parsed = GuardParser.parse(guard_string)

        if parsed.type == GuardType.UDF:
            # UDF guards historically used skip behavior (conditional_clause)
            default_behavior = GuardBehavior.SKIP
        else:
            # SQL guards historically used filter behavior (where_clause)
            default_behavior = GuardBehavior.FILTER

        return cls(condition=guard_string, on_false=default_behavior)

    def __repr__(self):
        return f"GuardConfig(condition='{self.condition}', on_false={self.on_false})"


def parse_guard_config(guard_data: Union[str, Dict[str, Any]]) -> GuardConfig:
    """
    Parse guard configuration from various formats.

    Args:
        guard_data: String (legacy) or dict (new format)

    Returns:
        GuardConfig instance

    Raises:
        ValueError: If format is invalid
    """
    if isinstance(guard_data, str):
        return GuardConfig.from_string(guard_data)
    elif isinstance(guard_data, dict):
        return GuardConfig.from_dict(guard_data)
    else:
        raise ValueError(f"Guard must be string or dict, got {type(guard_data)}")


__all__ = ["GuardBehavior", "GuardConfig", "parse_guard_config"]