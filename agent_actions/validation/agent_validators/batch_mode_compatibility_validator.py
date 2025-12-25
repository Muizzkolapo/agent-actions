"""
Backward compatibility module for batch mode compatibility validator.

This module re-exports VendorCompatibilityValidator as BatchModeCompatibilityValidator
for backward compatibility. New code should use VendorCompatibilityValidator directly.
"""

from agent_actions.validation.agent_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator as BatchModeCompatibilityValidator,
)

__all__ = ['BatchModeCompatibilityValidator']
