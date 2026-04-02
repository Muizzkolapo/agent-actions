"""Validator for vendor compatibility across batch and online modes."""

from agent_actions.config.types import RunMode
from agent_actions.output.response.config_fields import get_default
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class VendorCompatibilityValidator(BaseActionEntryValidator):
    """Validates vendor compatibility for batch and online modes."""

    VALID_BATCH_VENDORS = ActionConfigValidationUtilities.get_valid_batch_vendors()

    def validate(self, context) -> ActionEntryValidationResult:
        """Validate vendor compatibility based on run_mode."""
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []
        warnings = []

        raw_run_mode = normalized_entry.get("run_mode", get_default("run_mode"))
        run_mode = RunMode(raw_run_mode) if isinstance(raw_run_mode, str) else raw_run_mode

        if run_mode == RunMode.BATCH:
            kind = normalized_entry.get("kind", "").lower()
            if kind in ("tool", "hitl"):
                errors.append(
                    f"{desc} kind '{kind}' does not support batch processing. "
                    f"Tool and HITL actions execute synchronously. "
                    f"Set run_mode='online' or change kind to 'llm'."
                )

            model_vendor = str(normalized_entry.get("model_vendor", "")).lower()

            if model_vendor:
                if model_vendor == "tool":
                    vendors_str = ", ".join(sorted(self.VALID_BATCH_VENDORS))
                    errors.append(
                        f"{desc} 'tool' vendor does not support batch processing. "
                        f"Tool vendors require online mode for "
                        f"interactive execution. Use one of: {vendors_str} for "
                        f"batch mode, or set run_mode='online' for tool vendor."
                    )
                elif model_vendor not in self.VALID_BATCH_VENDORS:
                    vendors_str = ", ".join(sorted(self.VALID_BATCH_VENDORS))
                    warnings.append(
                        f"{desc} model_vendor '{model_vendor}' may not support "
                        f"batch processing. Verified batch-compatible vendors: "
                        f"{vendors_str}. If this vendor supports batch API, "
                        f"you can safely ignore this warning."
                    )

            batch_provider = normalized_entry.get("batch_provider")
            if batch_provider and not model_vendor:
                warnings.append(
                    f"{desc} 'batch_provider' is deprecated. Use 'model_vendor' instead. "
                    f"Found: batch_provider='{batch_provider}'"
                )
        if errors or warnings:
            return ActionEntryValidationResult(errors=errors, warnings=warnings)

        return ActionEntryValidationResult.success()


# Backward compatibility alias
BatchModeCompatibilityValidator = VendorCompatibilityValidator
