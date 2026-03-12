"""Vendor compatibility validator for pre-flight validation."""

from typing import Any

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)

# Vendor-specific feature support
VENDOR_CAPABILITIES = {
    "openai": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    },
    "anthropic": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens", "anthropic_version"],
    },
    "gemini": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    },
    "groq": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": False,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    },
    "mistral": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": False,
        "required_fields": ["model_name"],
        "optional_fields": ["api_key", "temperature", "max_tokens"],
    },
    "ollama": {
        "supports_json_mode": True,
        "supports_batch": False,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": ["base_url", "temperature", "max_tokens"],
    },
    "tool": {
        "supports_json_mode": True,  # N/A for tools, but set True to avoid false positives
        "supports_batch": True,  # Tools run in any mode
        "supports_tools": False,  # Tools don't call other tools
        "supports_vision": False,  # Tools don't process images directly
        "required_fields": [],
        "optional_fields": ["tool_name"],
    },
    "agac-provider": {
        "supports_json_mode": True,
        "supports_batch": True,
        "supports_tools": True,
        "supports_vision": True,
        "required_fields": ["model_name"],
        "optional_fields": [],
    },
}

# Valid vendor names
VALID_VENDORS = set(VENDOR_CAPABILITIES.keys())


class VendorCompatibilityValidator(BaseValidator):
    """Validates vendor configuration and feature compatibility."""

    def __init__(self) -> None:
        super().__init__()
        self.issues: list[ValidationIssue] = []

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Validate vendor configuration."""
        self.clear_errors()
        self.clear_warnings()
        self.issues = []

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary with 'agent_config' key.")
            return False

        agent_config = data.get("agent_config", {})
        config = config or {}

        agent_name = config.get("agent_name")
        mode = config.get("mode", "unknown")

        vendor = agent_config.get("model_vendor", "").lower()

        if not vendor:
            agent_type = agent_config.get("agent_type", "")
            if agent_type != "tool":
                self.add_error("model_vendor is required for non-tool agents")
                self.issues.append(
                    PreFlightErrorFormatter.create_vendor_config_issue(
                        message="Missing model_vendor in agent configuration",
                        vendor="unknown",
                        missing_fields=["model_vendor"],
                        agent_name=agent_name,
                    )
                )
            return not self.has_errors()

        if vendor not in VALID_VENDORS:
            self.add_error(f"Unknown vendor: {vendor}")
            self.issues.append(
                ValidationIssue(
                    message=f"Unknown vendor: {vendor}",
                    issue_type="error",
                    category="vendor",
                    available_refs=list(VALID_VENDORS),
                    hint=f"Use one of: {', '.join(sorted(VALID_VENDORS))}",
                    agent_name=agent_name,
                )
            )
            return False

        capabilities = VENDOR_CAPABILITIES[vendor]

        missing_fields = self._check_required_fields(agent_config, capabilities["required_fields"])
        if missing_fields:
            self.add_error(f"Missing required fields for {vendor}: {', '.join(missing_fields)}")
            self.issues.append(
                PreFlightErrorFormatter.create_vendor_config_issue(
                    message=f"Missing required fields for {vendor}",
                    vendor=vendor,
                    missing_fields=missing_fields,
                    agent_name=agent_name,
                )
            )

        unsupported = self._check_feature_compatibility(agent_config, capabilities, mode)
        if unsupported:
            for feature, reason in unsupported:
                self.add_error(f"Feature not supported by {vendor}: {feature} - {reason}")
            self.issues.append(
                PreFlightErrorFormatter.create_vendor_config_issue(
                    message=f"Unsupported features for {vendor}",
                    vendor=vendor,
                    unsupported_features=[f[0] for f in unsupported],
                    agent_name=agent_name,
                )
            )

        return not self.has_errors()

    def validate_vendor_config(
        self,
        agent_config: dict[str, Any],
        agent_name: str | None = None,
        mode: str = "unknown",
    ) -> bool:
        """Validate vendor config directly without wrapping in a data dict."""
        data = {"agent_config": agent_config}
        config = {"agent_name": agent_name, "mode": mode}
        return self.validate(data, config)

    def _check_required_fields(
        self, agent_config: dict[str, Any], required_fields: list[str]
    ) -> list[str]:
        """Return list of missing required field names."""
        missing = []
        for field in required_fields:
            if not agent_config.get(field):
                missing.append(field)
        return missing

    def _check_feature_compatibility(
        self,
        agent_config: dict[str, Any],
        capabilities: dict[str, Any],
        mode: str,
    ) -> list[tuple]:
        """Return list of (feature_name, reason) tuples for unsupported features."""
        unsupported = []

        if mode == "batch" and not capabilities.get("supports_batch"):
            unsupported.append(("batch", "Vendor does not support batch processing"))

        json_mode = agent_config.get("json_mode", True)
        if json_mode and not capabilities.get("supports_json_mode"):
            unsupported.append(("json_mode", "Vendor does not support JSON mode"))

        if agent_config.get("tools") and not capabilities.get("supports_tools"):
            unsupported.append(("tools", "Vendor does not support tool calling"))

        if agent_config.get("vision") and not capabilities.get("supports_vision"):
            unsupported.append(("vision", "Vendor does not support vision/images"))

        return unsupported

    def get_supported_vendors(self) -> set[str]:
        """Get set of supported vendor names."""
        return VALID_VENDORS.copy()

    def get_vendor_capabilities(self, vendor: str) -> dict[str, Any] | None:
        """Get capabilities for a specific vendor."""
        return VENDOR_CAPABILITIES.get(vendor.lower())

    def get_issues(self) -> list[ValidationIssue]:
        """Get the list of validation issues found."""
        return self.issues
