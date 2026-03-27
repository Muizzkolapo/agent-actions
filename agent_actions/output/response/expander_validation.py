"""Validation functions extracted from ActionExpander."""

from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.vendor import VendorType
from agent_actions.utils.constants import RESERVED_AGENT_NAMES


def validate_vendor_exists(vendor: str | None, action_name: str) -> None:
    """
    Validate vendor is a known/supported vendor.

    Args:
        vendor: Vendor name to validate
        action_name: Name of action for error context

    Raises:
        ConfigValidationError: If vendor is unknown
    """
    if not vendor:
        return
    valid_vendors = [v.value for v in VendorType]
    if vendor not in valid_vendors:
        raise ConfigValidationError(
            "model_vendor",
            f"Unknown vendor '{vendor}'",
            context={
                "action": action_name,
                "vendor": vendor,
                "supported_vendors": valid_vendors,
                "hint": f"Valid vendors: {', '.join(valid_vendors)}",
            },
        )


def validate_action_name(action_name: str | None) -> None:
    """Validate action name is not reserved."""
    if not action_name or not isinstance(action_name, str):
        raise ConfigValidationError(
            "name",
            "Action name must be a non-empty string",
            context={"action_name": action_name, "operation": "expand_actions_to_agents"},
        )

    normalized = action_name.strip().lower()
    if normalized in RESERVED_AGENT_NAMES:
        raise ConfigValidationError(
            "name",
            f"Reserved action name '{action_name}' cannot be used",
            context={
                "action_name": action_name,
                "reserved_names": sorted(RESERVED_AGENT_NAMES),
                "operation": "expand_actions_to_agents",
                "hint": "Rename the action to avoid reserved namespaces.",
            },
        )


def validate_required_fields(agent: dict[str, Any], action_name: str) -> None:
    """
    Validate that required configuration fields are present after hierarchy resolution.

    This validation ensures that essential fields (vendor, model, api_key) are defined
    at least once across the 3-level hierarchy (project -> workflow -> action).

    Args:
        agent: Agent configuration dict after hierarchy resolution
        action_name: Name of the action being validated (for error messages)

    Raises:
        ConfigValidationError: If any required field is missing
    """
    required_fields = {
        "model_vendor": agent.get("model_vendor"),
        "model_name": agent.get("model_name"),
        "api_key": agent.get("api_key"),
    }
    missing_fields = [field for field, value in required_fields.items() if not value]
    if missing_fields:
        field_display_names = {
            "model_vendor": "model_vendor",
            "model_name": "model_name",
            "api_key": "api_key",
        }
        missing_display = [field_display_names.get(f, f) for f in missing_fields]
        raise ConfigValidationError(
            config_key=", ".join(missing_fields),
            reason="Required configuration fields are missing after hierarchy resolution",
            context={
                "action_name": action_name,
                "missing_fields": missing_fields,
                "missing_display": missing_display,
                "operation": "expand_actions_to_agents",
                "hint": (
                    "Add missing fields to agent_actions.yml (project-level), "
                    "workflow defaults, or action config"
                ),
            },
        )
