"""Validator for vendor compatibility across batch and online modes."""

from agent_actions.config.types import RunMode
from agent_actions.llm.config.vendor import NON_LLM_VENDORS, ONLINE_ONLY_VENDORS
from agent_actions.output.response.config_fields import get_default
from agent_actions.validation.action_validators.base_action_validator import (
    ActionEntryValidationResult,
    BaseActionEntryValidator,
)


class VendorCompatibilityValidator(BaseActionEntryValidator):
    """Validates vendor compatibility for batch and online modes."""

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
            model_vendor = str(normalized_entry.get("model_vendor", "")).lower()
            # The pipeline runs these online inside a batch run.
            runs_online = kind in ONLINE_ONLY_VENDORS or model_vendor in ONLINE_ONLY_VENDORS

            if model_vendor and not runs_online:
                # Imported here: the preflight module loads the client registry.
                from agent_actions.validation.preflight.vendor_compatibility_validator import (
                    CLIENT_REGISTRY,
                    batch_vendors,
                    supports_batch,
                )

                if model_vendor not in CLIENT_REGISTRY or model_vendor in NON_LLM_VENDORS:
                    vendors_str = ", ".join(batch_vendors())
                    warnings.append(
                        f"{desc} model_vendor '{model_vendor}' may not support "
                        f"batch processing. Verified batch-compatible vendors: "
                        f"{vendors_str}. If this vendor supports batch API, "
                        f"you can safely ignore this warning."
                    )
                elif supports_batch(model_vendor) is False:
                    errors.append(
                        f"{desc}: vendor '{model_vendor}' does not support run_mode: batch. "
                        "Set run_mode: online."
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
