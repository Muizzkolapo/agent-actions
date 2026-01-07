"""
Validator for vendor compatibility across batch and online modes.
"""

from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult,
)


class VendorCompatibilityValidator(BaseAgentEntryValidator):
    """
    Validates vendor compatibility for batch and online modes.

    Batch processing is only supported for specific vendors due to batch API availability:
    - openai
    - gemini
    - anthropic
    - groq
    - mistral

    Online/realtime mode accepts all vendors including custom integrations.

    Tool vendors cannot use batch mode (batch requires LLM API support).

    Complexity: CC ~5
    """

    VALID_BATCH_VENDORS = {"openai", "gemini", "anthropic", "groq", "mistral"}

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate vendor compatibility based on run_mode.

        Args:
            context: Validation context with normalized_entry and description

        Returns:
            Validation result with errors/warnings

        Validation logic:
        - run_mode='batch': Validate vendor is in VALID_BATCH_VENDORS
        - run_mode='online': No vendor validation (all vendors accepted)
        - Tool vendor + batch mode: Error (tool vendors require realtime)
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []
        warnings = []

        # Get run_mode (default to 'online')
        run_mode = str(normalized_entry.get("run_mode", "online")).lower()

        # Only validate vendor compatibility for batch mode
        if run_mode == "batch":
            model_vendor = str(normalized_entry.get("model_vendor", "")).lower()

            # Check if vendor supports batch processing
            if model_vendor:
                if model_vendor == "tool":
                    # Special error for tool vendor
                    vendors_str = ", ".join(sorted(self.VALID_BATCH_VENDORS))
                    errors.append(
                        f"{desc} 'tool' vendor does not support batch processing. "
                        f"Tool vendors require realtime/online mode for "
                        f"interactive execution. Use one of: {vendors_str} for "
                        f"batch mode, or set run_mode='online' for tool vendor."
                    )
                elif model_vendor not in self.VALID_BATCH_VENDORS:
                    # Generic unsupported vendor warning (may support batch)
                    vendors_str = ", ".join(sorted(self.VALID_BATCH_VENDORS))
                    warnings.append(
                        f"{desc} model_vendor '{model_vendor}' may not support "
                        f"batch processing. Verified batch-compatible vendors: "
                        f"{vendors_str}. If this vendor supports batch API, "
                        f"you can safely ignore this warning."
                    )

            # Check for deprecated batch_provider field
            batch_provider = normalized_entry.get("batch_provider")
            if batch_provider and not model_vendor:
                warnings.append(
                    f"{desc} 'batch_provider' is deprecated. Use 'model_vendor' instead. "
                    f"Found: batch_provider='{batch_provider}'"
                )
        # Online mode: No vendor validation needed (all vendors accepted)

        if errors or warnings:
            return AgentEntryValidationResult(errors=errors, warnings=warnings)

        return AgentEntryValidationResult.success()


# Backward compatibility alias
BatchModeCompatibilityValidator = VendorCompatibilityValidator
