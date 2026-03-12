"""Field reference validation against the workflow dependency graph."""

import logging
from typing import Any, Dict, List, Optional, Union

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .exceptions import DependencyValidationError
from .reference_parser import ParsedReference, ReferenceParser
from .schema_field_validator import SchemaFieldValidator

logger = logging.getLogger(__name__)


class ReferenceValidator:
    """Validates field references against the workflow dependency graph."""

    def __init__(self, strict_dependencies: bool = True):
        self.strict_dependencies = strict_dependencies
        self._parser = ReferenceParser()
        self._schema_validator = SchemaFieldValidator()

    def validate(
        self,
        references: List[Union[str, ParsedReference]],
        agent_config: Dict[str, Any],
        agent_indices: Dict[str, int],
        current_agent_name: Optional[str] = None,
    ) -> List[str]:
        """Validate references against dependency graph. Returns list of error messages."""
        errors = []

        if current_agent_name is None:
            current_agent_name = agent_config.get("agent_type", "unknown")

        current_idx = agent_indices.get(current_agent_name, 999)

        declared_deps = set(agent_config.get("dependencies", []))

        for ref in references:
            if isinstance(ref, str):
                try:
                    ref = self._parser.parse(ref)
                except (ValueError, TypeError) as e:
                    errors.append(f"Invalid reference syntax: '{ref}' - {e}")
                    continue

            action_name = ref.action_name

            if action_name in SPECIAL_NAMESPACES:
                continue

            if action_name not in agent_indices:
                available = sorted(agent_indices.keys())
                errors.append(
                    f"Action '{action_name}' referenced in guard but not found in workflow. "
                    f"Available actions: {available}"
                )
                continue

            action_idx = agent_indices[action_name]
            if action_idx >= current_idx:
                errors.append(
                    f"Action '{action_name}' (node_{action_idx}) cannot be referenced "
                    f"by '{current_agent_name}' (node_{current_idx}) - "
                    f"it is not upstream (runs at same time or later)."
                )
                continue

            if self.strict_dependencies and action_name not in declared_deps:
                suggested_deps = list(declared_deps) + [action_name]
                errors.append(
                    f"Action '{action_name}' referenced in guard but not in dependencies. "
                    f"Add it to dependencies: {sorted(suggested_deps)}"
                )

        return errors

    def validate_strict(
        self,
        references: List[Union[str, ParsedReference]],
        agent_config: Dict[str, Any],
        agent_indices: Dict[str, int],
        current_agent_name: Optional[str] = None,
    ) -> None:
        """Validate references and raise DependencyValidationError if invalid."""
        errors = self.validate(
            references=references,
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name=current_agent_name,
        )

        if errors:
            agent_name = current_agent_name or agent_config.get("agent_type", "unknown")
            raise DependencyValidationError(
                f"Invalid guard references in '{agent_name}':\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def extract_and_validate(
        self,
        guard_condition: str,
        agent_config: Dict[str, Any],
        agent_indices: Dict[str, int],
        current_agent_name: Optional[str] = None,
    ) -> List[str]:
        """Extract references from guard condition and validate them."""
        # Parse references from guard condition
        references = self._parser.parse_batch(guard_condition)

        if not references:
            return []

        return self.validate(
            references=references,
            agent_config=agent_config,
            agent_indices=agent_indices,
            current_agent_name=current_agent_name,
        )

    def get_referenced_actions(self, guard_condition: str) -> List[str]:
        """Extract unique action names referenced in a guard condition."""
        references = self._parser.parse_batch(guard_condition)

        action_names = set()
        for ref in references:
            if ref.action_name not in SPECIAL_NAMESPACES:
                action_names.add(ref.action_name)

        return sorted(action_names)

    def validate_against_schemas(
        self,
        references: List[Union[str, ParsedReference]],
        action_schemas: Dict[str, Dict[str, Any]],
        _current_agent_name: Optional[str] = None,
    ) -> List[str]:
        """Validate field references against action output schemas."""
        errors = []

        for ref in references:
            if isinstance(ref, str):
                try:
                    ref = self._parser.parse(ref)
                except (ValueError, TypeError) as e:
                    errors.append(f"Invalid reference syntax: '{ref}' - {e}")
                    continue

            action_name = ref.action_name

            if action_name in SPECIAL_NAMESPACES:
                continue

            if action_name not in action_schemas:
                continue

            schema = action_schemas[action_name]
            validation_result = self._schema_validator.validate_field_path(
                field_path=ref.field_path, json_schema=schema, action_name=action_name
            )

            if not validation_result.exists:
                errors.append(validation_result.error)

        return errors

    def validate_with_schemas(
        self, references: List[Union[str, ParsedReference]], validation_context: Dict[str, Any]
    ) -> List[str]:
        """Perform both dependency graph and schema field validation."""
        dep_errors = self.validate(
            references=references,
            agent_config=validation_context["agent_config"],
            agent_indices=validation_context["agent_indices"],
            current_agent_name=validation_context.get("current_agent_name"),
        )

        schema_errors = self.validate_against_schemas(
            references=references, action_schemas=validation_context["action_schemas"]
        )

        return dep_errors + schema_errors
