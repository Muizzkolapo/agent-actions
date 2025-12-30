"""Vendor compatibility validator for pre-flight validation.

Validates that vendor configuration is valid and supports requested features
before any LLM processing begins.
"""

from typing import Any, Dict, List, Optional, Set

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
        "supports_json_mode": False,
        "supports_batch": False,
        "supports_tools": False,
        "supports_vision": False,
        "required_fields": [],
        "optional_fields": ["tool_name"],
    },
}

# Valid vendor names
VALID_VENDORS = set(VENDOR_CAPABILITIES.keys())


class VendorCompatibilityValidator(BaseValidator):
    """Validates vendor configuration and feature compatibility.

    This validator checks that vendor config has required fields and
    that requested features are supported by the vendor.

    Attributes:
        issues: List of ValidationIssue objects found during validation
    """

    def __init__(self) -> None:
        super().__init__()
        self.issues: List[ValidationIssue] = []

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Validate vendor configuration.

        Args:
            data: Dictionary containing:
                - 'agent_config': The agent configuration dict
            config: Optional config with:
                - 'agent_name': Name of the agent for error messages
                - 'mode': Execution mode ('batch' or 'online')

        Returns:
            bool: True if vendor config is valid, False otherwise
        """
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

        # Get vendor from config
        vendor = agent_config.get("model_vendor", "").lower()

        if not vendor:
            # No vendor specified - might be a tool agent
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

        # Validate vendor is known
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

        # Get vendor capabilities
        capabilities = VENDOR_CAPABILITIES[vendor]

        # Check required fields
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

        # Check feature compatibility
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
        agent_config: Dict[str, Any],
        agent_name: Optional[str] = None,
        mode: str = "unknown",
    ) -> bool:
        """Convenience method to validate vendor config directly.

        Args:
            agent_config: Agent configuration dictionary
            agent_name: Optional agent name for error messages
            mode: Execution mode

        Returns:
            bool: True if vendor config is valid
        """
        data = {"agent_config": agent_config}
        config = {"agent_name": agent_name, "mode": mode}
        return self.validate(data, config)

    def _check_required_fields(
        self, agent_config: Dict[str, Any], required_fields: List[str]
    ) -> List[str]:
        """Check if required fields are present.

        Args:
            agent_config: Agent configuration
            required_fields: List of required field names

        Returns:
            List of missing field names
        """
        missing = []
        for field in required_fields:
            if not agent_config.get(field):
                missing.append(field)
        return missing

    def _check_feature_compatibility(
        self,
        agent_config: Dict[str, Any],
        capabilities: Dict[str, Any],
        mode: str,
    ) -> List[tuple]:
        """Check if requested features are supported by vendor.

        Args:
            agent_config: Agent configuration
            capabilities: Vendor capability dict
            mode: Execution mode

        Returns:
            List of (feature_name, reason) tuples for unsupported features
        """
        unsupported = []

        # Check batch mode support
        if mode == "batch" and not capabilities.get("supports_batch"):
            unsupported.append(("batch", "Vendor does not support batch processing"))

        # Check json_mode
        json_mode = agent_config.get("json_mode", True)
        if json_mode and not capabilities.get("supports_json_mode"):
            unsupported.append(("json_mode", "Vendor does not support JSON mode"))

        # Check tools
        if agent_config.get("tools") and not capabilities.get("supports_tools"):
            unsupported.append(("tools", "Vendor does not support tool calling"))

        # Check vision
        if agent_config.get("vision") and not capabilities.get("supports_vision"):
            unsupported.append(("vision", "Vendor does not support vision/images"))

        return unsupported

    def get_supported_vendors(self) -> Set[str]:
        """Get set of supported vendor names.

        Returns:
            Set of valid vendor names
        """
        return VALID_VENDORS.copy()

    def get_vendor_capabilities(self, vendor: str) -> Optional[Dict[str, Any]]:
        """Get capabilities for a specific vendor.

        Args:
            vendor: Vendor name

        Returns:
            Capabilities dict or None if vendor not found
        """
        return VENDOR_CAPABILITIES.get(vendor.lower())

    def get_issues(self) -> List[ValidationIssue]:
        """Get the list of validation issues found.

        Returns:
            List of ValidationIssue objects
        """
        return self.issues
