"""Orchestrator for agent entry validation."""

from typing import Dict, Any, List, Optional
from pathlib import Path
from agent_actions.validation.agent_validators.base_agent_validator import (
    BaseAgentEntryValidator,
)
from agent_actions.validation.agent_validators.agent_entry_structure_validator import (
    AgentEntryStructureValidator,
)
from agent_actions.validation.agent_validators.agent_required_fields_validator import (
    AgentRequiredFieldsValidator,
)
from agent_actions.validation.agent_validators.agent_type_specific_validator import (
    AgentTypeSpecificValidator,
)
from agent_actions.validation.agent_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.agent_validators.optional_field_type_validator import (
    OptionalFieldTypeValidator,
)
from agent_actions.validation.agent_validators.granularity_output_field_validator import (
    GranularityAndOutputFieldValidator,
)
from agent_actions.validation.agent_validators.inline_schema_validator import (
    InlineSchemaValidator,
)
from agent_actions.validation.agent_validators.unknown_keys_detector import (
    UnknownKeysDetector,
)
from agent_actions.validation.utils.agent_config_validation_utilities import (
    AgentConfigValidationUtilities,
)


class AgentEntryValidationContext:
    """Encapsulates validation context passed to all validators."""

    def __init__(
        self, entry: Dict[str, Any], agent_name_context: str, project_root: Optional[Path] = None
    ):
        self.entry = entry
        self.agent_name_context = agent_name_context
        self.project_root = project_root

        self.normalized_entry = AgentConfigValidationUtilities.normalize_entry_keys_to_lowercase(
            entry
        )

        self.description = AgentConfigValidationUtilities.format_validation_context(
            entry, agent_name_context
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"AgentEntryValidationContext(agent={self.agent_name_context}, "
            f"has_project_root={self.project_root is not None})"
        )


class AgentEntryValidationOrchestrator:
    """Orchestrates agent entry validation through a chain of specialized validators."""

    def __init__(self):
        """Initialize orchestrator with validation chain."""
        self._errors: List[str] = []
        self._warnings: List[str] = []

        # Order matters: structural checks first, then semantic checks
        self._validators: List[BaseAgentEntryValidator] = [
            AgentEntryStructureValidator(),  # Must run first - checks if dict
            AgentRequiredFieldsValidator(),  # Check required keys present
            AgentTypeSpecificValidator(),  # Type-specific requirements
            VendorCompatibilityValidator(),  # Vendor compatibility
            OptionalFieldTypeValidator(),  # Optional field type checks
            GranularityAndOutputFieldValidator(),  # Granularity + output
            InlineSchemaValidator(),  # Complex schema validation
            UnknownKeysDetector(),  # Typo detection (warnings)
        ]

    def validate_agent_entry(
        self, entry: Dict[str, Any], agent_name_context: str, project_root: Optional[Path] = None
    ) -> bool:
        """Validate a single agent entry through the validation chain."""
        self._errors.clear()
        self._warnings.clear()

        context = AgentEntryValidationContext(
            entry=entry, agent_name_context=agent_name_context, project_root=project_root
        )

        for validator in self._validators:
            result = validator.validate(context)

            self._errors.extend(result.errors)
            self._warnings.extend(result.warnings)

            if result.is_critical_failure:
                break

        return len(self._errors) == 0

    def get_validation_errors(self) -> List[str]:
        """Get all collected validation errors."""
        return self._errors.copy()

    def get_validation_warnings(self) -> List[str]:
        """Get all collected validation warnings."""
        return self._warnings.copy()
