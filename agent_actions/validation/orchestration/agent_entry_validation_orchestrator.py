"""
Orchestrator for agent entry validation.

Coordinates execution of specialized validators in a chain, handling:
- Early termination on critical structural failures
- Shared context and utilities access
- Error and warning aggregation
"""

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
    """
    Encapsulates validation context passed to all validators.

    This provides a clean way to pass shared data without polluting
    method signatures with many parameters.
    """

    def __init__(
        self, entry: Dict[str, Any], agent_name_context: str, project_root: Optional[Path] = None
    ):
        self.entry = entry
        self.agent_name_context = agent_name_context
        self.project_root = project_root

        # Case-insensitive normalized entry (cached for reuse)
        self.normalized_entry = AgentConfigValidationUtilities.normalize_entry_keys_to_lowercase(
            entry
        )

        # Formatted description for error messages (cached)
        self.description = AgentConfigValidationUtilities.format_validation_context(
            entry, agent_name_context
        )

    def __repr__(self) -> str:
        """Return string representation of context."""
        return (
            f"AgentEntryValidationContext(agent={self.agent_name_context}, "
            f"has_project_root={self.project_root is not None})"
        )

    def is_valid(self) -> bool:
        """
        Check if context is properly configured.

        Returns:
            bool: True if entry is a dict and description is set
        """
        return isinstance(self.entry, dict) and bool(self.description)


class AgentEntryValidationOrchestrator:
    """
    Orchestrates agent entry validation through a chain of specialized validators.

    This orchestrator:
    1. Executes validators in a specific order
    2. Allows early termination on critical failures
    3. Aggregates errors and warnings from all validators
    4. Provides shared utilities and context to validators

    Complexity: CC ~5 (just orchestration logic)
    """

    def __init__(self):
        """Initialize orchestrator with validation chain."""
        self._errors: List[str] = []
        self._warnings: List[str] = []

        # Build validation chain in execution order
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
        """
        Validate a single agent entry through the validation chain.

        Args:
            entry: Agent configuration entry to validate
            agent_name_context: Name/context for error messages
            project_root: Optional project root for path resolution

        Returns:
            bool: True if validation passed (no errors), False otherwise
        """
        self._errors.clear()
        self._warnings.clear()

        # Create shared context
        context = AgentEntryValidationContext(
            entry=entry, agent_name_context=agent_name_context, project_root=project_root
        )

        # Execute validation chain
        for validator in self._validators:
            result = validator.validate(context)

            # Collect errors and warnings
            self._errors.extend(result.errors)
            self._warnings.extend(result.warnings)

            # Early termination on critical failure
            if result.is_critical_failure:
                # Stop chain - no point validating further if structure is broken
                break

        return len(self._errors) == 0

    def get_validation_errors(self) -> List[str]:
        """Get all validation errors collected from validators."""
        return self._errors.copy()

    def get_validation_warnings(self) -> List[str]:
        """Get all validation warnings collected from validators."""
        return self._warnings.copy()
