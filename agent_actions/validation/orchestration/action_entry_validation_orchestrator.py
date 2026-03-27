"""Orchestrator for action entry validation."""

from pathlib import Path
from typing import Any

from agent_actions.validation.action_validators.action_entry_structure_validator import (
    ActionEntryStructureValidator,
)
from agent_actions.validation.action_validators.action_required_fields_validator import (
    ActionRequiredFieldsValidator,
)
from agent_actions.validation.action_validators.action_type_specific_validator import (
    ActionTypeSpecificValidator,
)
from agent_actions.validation.action_validators.base_action_validator import (
    BaseActionEntryValidator,
)
from agent_actions.validation.action_validators.granularity_output_field_validator import (
    GranularityAndOutputFieldValidator,
)
from agent_actions.validation.action_validators.inline_schema_validator import (
    InlineSchemaValidator,
)
from agent_actions.validation.action_validators.optional_field_type_validator import (
    OptionalFieldTypeValidator,
)
from agent_actions.validation.action_validators.unknown_keys_detector import (
    UnknownKeysDetector,
)
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.utils.action_config_validation_utilities import (
    ActionConfigValidationUtilities,
)


class ActionEntryValidationContext:
    """Encapsulates validation context passed to all validators."""

    def __init__(
        self, entry: dict[str, Any], agent_name_context: str, project_root: Path | None = None
    ):
        self.entry = entry
        self.agent_name_context = agent_name_context
        self.project_root = project_root

        self.normalized_entry = ActionConfigValidationUtilities.normalize_entry_keys_to_lowercase(
            entry
        )

        self.description = ActionConfigValidationUtilities.format_validation_context(
            entry, agent_name_context
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"ActionEntryValidationContext(agent={self.agent_name_context}, "
            f"has_project_root={self.project_root is not None})"
        )


class ActionEntryValidationOrchestrator:
    """Orchestrates action entry validation through a chain of specialized validators."""

    def __init__(self):
        """Initialize orchestrator with validation chain."""
        self._errors: list[str] = []
        self._warnings: list[str] = []

        # Order matters: structural checks first, then semantic checks
        self._validators: list[BaseActionEntryValidator] = [
            ActionEntryStructureValidator(),  # Must run first - checks if dict
            ActionRequiredFieldsValidator(),  # Check required keys present
            ActionTypeSpecificValidator(),  # Type-specific requirements
            VendorCompatibilityValidator(),  # Vendor compatibility
            OptionalFieldTypeValidator(),  # Optional field type checks
            GranularityAndOutputFieldValidator(),  # Granularity + output
            InlineSchemaValidator(),  # Complex schema validation
            UnknownKeysDetector(),  # Typo detection (warnings)
        ]

    def validate_action_entry(
        self, entry: dict[str, Any], agent_name_context: str, project_root: Path | None = None
    ) -> bool:
        """Validate a single action entry through the validation chain."""
        self._errors.clear()
        self._warnings.clear()

        context = ActionEntryValidationContext(
            entry=entry, agent_name_context=agent_name_context, project_root=project_root
        )

        for validator in self._validators:
            result = validator.validate(context)

            self._errors.extend(result.errors)
            self._warnings.extend(result.warnings)

            if result.is_critical_failure:
                break

        return len(self._errors) == 0

    def get_validation_errors(self) -> list[str]:
        """Get all collected validation errors."""
        return self._errors.copy()

    def get_validation_warnings(self) -> list[str]:
        """Get all collected validation warnings."""
        return self._warnings.copy()
