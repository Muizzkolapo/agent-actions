"""Vendor compatibility validator for pre-flight validation."""

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

from agent_actions.llm.realtime.services.invocation import CLIENT_REGISTRY
from agent_actions.output.response.config_fields import get_default
from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)

# Single source of truth: runtime CLIENT_REGISTRY defines valid vendors.
VALID_VENDORS = set(CLIENT_REGISTRY.keys())


def _resolve_capabilities(vendor: str) -> dict[str, Any] | None:
    """Resolve CAPABILITIES from the client class for *vendor*.

    Handles lazy string entries in CLIENT_REGISTRY (e.g. gemini) by importing
    them on demand, avoiding eager SDK imports at module level.

    Returns ``None`` if the resolved class has no ``CAPABILITIES`` attribute
    or if the provider's SDK is not installed.
    """
    entry = CLIENT_REGISTRY.get(vendor)
    if entry is None:
        return None
    if isinstance(entry, str):
        module_path, class_name = entry.split(":", 1)
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
        except (ImportError, AttributeError):
            logger.debug("Skipping capabilities for '%s': SDK not available", vendor)
            return None
        CLIENT_REGISTRY[vendor] = cls
    else:
        cls = entry
    caps = getattr(cls, "CAPABILITIES", None)
    if not caps:
        return None
    return caps  # type: ignore[no-any-return]


def get_vendor_capabilities_map() -> dict[str, dict[str, Any]]:
    """Build the full vendor→capabilities mapping on demand.

    Provided for external consumers that need the complete dict.
    """
    result: dict[str, dict[str, Any]] = {}
    for vendor in CLIENT_REGISTRY:
        caps = _resolve_capabilities(vendor)
        if caps is not None:
            result[vendor] = caps
    return result


_VENDOR_CAPABILITIES: dict | None = None


def _get_vendor_capabilities() -> dict:
    """Lazy-initialize vendor capabilities on first access."""
    global _VENDOR_CAPABILITIES
    if _VENDOR_CAPABILITIES is None:
        _VENDOR_CAPABILITIES = get_vendor_capabilities_map()
    return _VENDOR_CAPABILITIES


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

        capabilities = _resolve_capabilities(vendor)
        if capabilities is None:
            # Client class has no CAPABILITIES — skip deeper checks.
            return True

        missing_fields = self._check_required_fields(agent_config, capabilities["required_fields"])  # type: ignore[arg-type]
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

        json_mode = agent_config.get("json_mode", get_default("json_mode"))
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
        return _resolve_capabilities(vendor)

    def get_issues(self) -> list[ValidationIssue]:
        """Get the list of validation issues found."""
        return self.issues

    @classmethod
    def clear_cache(cls) -> None:
        """Reset the lazy-loaded vendor capabilities cache. Call from test teardown."""
        global _VENDOR_CAPABILITIES
        _VENDOR_CAPABILITIES = None
