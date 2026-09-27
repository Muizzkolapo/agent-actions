"""Validation functions extracted from ActionExpander."""

from typing import Any

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.vendor import VendorType
from agent_actions.utils.constants import RESERVED_AGENT_NAMES, RUNTIME_BUS_NAMESPACES


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


def _declared_output_fields(agent: dict[str, Any]) -> set[str]:
    """Field names an action's output schema declares, across the shapes one arrives in.

    Rendering inlines a schema named by file before expansion, so a declared schema is
    readable here whichever way the author wrote it. Nothing is declared when the action
    has no schema at all, and the framework validates no output in that case either.
    """
    names: set[str] = set()
    for source in (agent.get("schema"), agent.get("json_output_schema")):
        if not isinstance(source, dict):
            continue
        fields = source.get("fields")
        if isinstance(fields, list):
            names |= {
                str(name)
                for entry in fields
                if isinstance(entry, dict) and (name := entry.get("id") or entry.get("name"))
            }
            continue
        properties = source.get("properties")
        if isinstance(properties, dict):
            names |= {str(key) for key in properties}
            continue
        # Shorthand: {field_name: type}. Every value is a type string.
        if all(isinstance(value, str) for value in source.values()):
            names |= {str(key) for key in source}
    return names


def validate_version_merge_output_namespaces(agent: dict[str, Any], action_name: str) -> None:
    """Refuse a version-merge tool whose output declares a framework namespace's name.

    Such a tool's output is spread flat over record content rather than nested under the
    action's own name, so its fields are content's own top-level keys. A field named for a
    framework namespace therefore lands where that namespace goes and replaces it, which
    for ``source`` leaves the record with nothing a later action can resolve the document
    from. Both names are legitimate on their own, so the collision is settled here, where
    renaming the field still costs nothing, rather than per record once data is at stake.
    """
    if agent.get("kind") != "tool" or not agent.get("version_consumption_config"):
        return
    taken = sorted(_declared_output_fields(agent) & RUNTIME_BUS_NAMESPACES)
    if not taken:
        return
    raise ConfigValidationError(
        "schema",
        f"Version-merge tool '{action_name}' declares output field(s) "
        f"{', '.join(repr(name) for name in taken)} naming a framework namespace",
        context={
            "action": action_name,
            "fields": taken,
            "framework_namespaces": sorted(RUNTIME_BUS_NAMESPACES),
            "operation": "expand_actions_to_agents",
            "hint": (
                "A version-merge tool's output is spread flat over record content, so "
                "these fields would replace the namespaces of the same name. Rename "
                f"{'them' if len(taken) > 1 else 'it'} in the action's schema."
            ),
        },
    )
