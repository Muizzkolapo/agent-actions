"""Consolidated guard configuration with explicit behavior control."""

from enum import Enum
from typing import Any

from agent_actions.errors import ConfigValidationError

from .guard_parser import GuardParser, GuardType


class GuardBehavior(str, Enum):
    """Behavior options when guard condition fails."""

    SKIP = "skip"
    FILTER = "filter"
    WRITE_TO = "write_to"
    REPROCESS = "reprocess"


class GuardConfig:
    """Consolidated guard configuration with condition and behavior control."""

    def __init__(self, condition: str, on_false: GuardBehavior | str):
        """Initialize guard configuration."""
        self.condition = condition
        if not isinstance(on_false, GuardBehavior | str):
            raise ConfigValidationError(
                "on_false",
                f"on_false must be a GuardBehavior or string, got {type(on_false).__name__}",
                context={"on_false_type": str(type(on_false)), "on_false_value": repr(on_false)},
            )
        try:
            self.on_false = GuardBehavior(on_false) if isinstance(on_false, str) else on_false
        except ValueError as e:
            raise ConfigValidationError(
                "on_false",
                f"Invalid guard behavior '{on_false}'. Valid values: {[b.value for b in GuardBehavior]}",
                context={"on_false_value": on_false},
            ) from e
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
    def from_dict(cls, config_dict: dict[str, Any]) -> "GuardConfig":
        """Create GuardConfig from a dictionary with 'condition' and 'on_false' keys.

        Raises:
            ConfigValidationError: If required keys are missing or type is wrong
        """
        if not isinstance(config_dict, dict):
            raise ConfigValidationError(
                "guard_config_type",
                "Guard config must be a dictionary",
                context={"config_type": str(type(config_dict)), "operation": "parse_guard_config"},
            )
        if "condition" not in config_dict:
            raise ConfigValidationError(
                "guard_config_condition",
                "Guard dict must have 'condition' key",
                context={
                    "config_keys": list(config_dict.keys()),
                    "operation": "parse_guard_config",
                },
            )
        condition = config_dict["condition"]
        on_false = config_dict.get("on_false", "filter")
        return cls(condition=condition, on_false=on_false)

    @classmethod
    def from_string(cls, guard_string: str) -> "GuardConfig":
        """Create GuardConfig from a legacy guard expression string."""
        parsed = GuardParser.parse(guard_string)
        if parsed.type == GuardType.UDF:
            default_behavior = GuardBehavior.SKIP
        else:
            default_behavior = GuardBehavior.FILTER
        return cls(condition=guard_string, on_false=default_behavior)

    def __repr__(self):
        return f"GuardConfig(condition='{self.condition}', on_false={self.on_false})"


def parse_guard_config(guard_data: str | dict[str, Any]) -> GuardConfig:
    """Parse guard configuration from string (legacy) or dict format.

    Raises:
        ConfigValidationError: If format is invalid
    """
    if isinstance(guard_data, str):
        return GuardConfig.from_string(guard_data)
    if isinstance(guard_data, dict):
        return GuardConfig.from_dict(guard_data)

    raise ConfigValidationError(
        "guard_data_type",
        f"Guard must be string or dict, got {type(guard_data)}",
        context={"guard_type": str(type(guard_data)), "operation": "parse_guard_config"},
    )


__all__ = ["GuardBehavior", "GuardConfig", "parse_guard_config"]
