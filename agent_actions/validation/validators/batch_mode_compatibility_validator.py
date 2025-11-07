"""
Validator for batch mode configuration and vendor compatibility.

Checks:
- Batch mode requires compatible model vendor
- Tool vendor cannot use batch mode
- Deprecated batch_provider field warnings
"""

from agent_actions.validation.validators.base_agent_validator import (
    BaseAgentEntryValidator,
    AgentEntryValidationResult
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities
)


class BatchModeCompatibilityValidator(BaseAgentEntryValidator):
    """
    Validates batch mode configuration and vendor compatibility.

    Batch processing is only supported for specific vendors:
    - openai
    - gemini
    - anthropic

    Tool vendors cannot use batch mode.

    Complexity: CC ~5
    """

    def validate(self, context) -> AgentEntryValidationResult:
        """
        Validate batch mode configuration.

        Args:
            context: Validation context

        Returns:
            Validation result with errors/warnings
        """
        normalized_entry = context.normalized_entry
        desc = context.description

        errors = []
        warnings = []

        # Get run_mode (default to empty string)
        run_mode = str(normalized_entry.get('run_mode', '')).lower()

        # Only validate if run_mode is 'batch'
        if run_mode == 'batch':
            model_vendor = str(normalized_entry.get('model_vendor', '')).lower()
            valid_batch_vendors = AgentConfigValidationUtilities.get_valid_batch_vendors()

            # Check if vendor supports batch processing
            if model_vendor and model_vendor not in valid_batch_vendors:
                if model_vendor == 'tool':
                    # Special error for tool vendor
                    errors.append(
                        f"{desc} 'tool' vendor does not support batch processing. "
                        f"Use one of: {', '.join(sorted(valid_batch_vendors))} for batch mode."
                    )
                else:
                    # Generic unsupported vendor error
                    errors.append(
                        f"{desc} model_vendor '{model_vendor}' is not supported for "
                        f"batch processing. Supported batch providers: "
                        f"{', '.join(sorted(valid_batch_vendors))}"
                    )

            # Check for deprecated batch_provider field
            batch_provider = normalized_entry.get('batch_provider')
            if batch_provider and not model_vendor:
                warnings.append(
                    f"{desc} 'batch_provider' is deprecated. Use 'model_vendor' instead. "
                    f"Found: batch_provider='{batch_provider}'"
                )

        if errors or warnings:
            return AgentEntryValidationResult(errors=errors, warnings=warnings)

        return AgentEntryValidationResult.success()
