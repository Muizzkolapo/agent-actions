"""
Validates field references against the workflow dependency graph.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from agent_actions.utils.constants import SPECIAL_NAMESPACES

from .exceptions import DependencyValidationError
from .reference_parser import ParsedReference, ReferenceParser
from .schema_field_validator import SchemaFieldValidator

logger = logging.getLogger(__name__)


class ReferenceValidator:
    """
    Validates field references against the workflow dependency graph.

    Checks that:
    1. Referenced actions exist in the workflow
    2. Referenced actions are upstream (lower index) of current action
    3. Referenced actions are in declared dependencies (optional strict check)
    """

    def __init__(self, strict_dependencies: bool = True):
        """
        Initialize validator.

        Args:
            strict_dependencies: If True, require referenced actions to be in
                                declared dependencies. If False, allow any
                                upstream action.
        """
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
        """
        Validate references against dependency graph.

        Args:
            references: References to validate (strings or ParsedReference)
            agent_config: Current agent configuration (needs 'dependencies' key)
            agent_indices: Mapping of agent names to their execution indices
            current_agent_name: Name of current agent (for index lookup)

        Returns:
            List of error messages (empty if all valid)

        Raises:
            DependencyValidationError: If validation fails (use validate_strict)
        """
        errors = []

        # Get current agent info
        if current_agent_name is None:
            current_agent_name = agent_config.get("agent_type", "unknown")

        current_idx = agent_indices.get(current_agent_name, 999)

        # Get declared dependencies
        declared_deps = set(agent_config.get("dependencies", []))

        for ref in references:
            # Parse if string
            if isinstance(ref, str):
                try:
                    ref = self._parser.parse(ref)
                except (ValueError, TypeError) as e:
                    errors.append(f"Invalid reference syntax: '{ref}' - {e}")
                    continue

            action_name = ref.action_name

            # Skip special namespaces (always allowed)
            if action_name in SPECIAL_NAMESPACES:
                continue

            # Check 1: Action exists in workflow
            if action_name not in agent_indices:
                available = sorted(agent_indices.keys())
                errors.append(
                    f"Action '{action_name}' referenced in guard but not found in workflow. "
                    f"Available actions: {available}"
                )
                continue

            # Check 2: Action is upstream (lower index)
            action_idx = agent_indices[action_name]
            if action_idx >= current_idx:
                errors.append(
                    f"Action '{action_name}' (node_{action_idx}) cannot be referenced "
                    f"by '{current_agent_name}' (node_{current_idx}) - "
                    f"it is not upstream (runs at same time or later)."
                )
                continue

            # Check 3: Action is in declared dependencies (strict mode)
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
        """
        Validate references and raise exception if invalid.

        Args:
            references: References to validate
            agent_config: Current agent configuration
            agent_indices: Mapping of agent names to indices
            current_agent_name: Name of current agent

        Raises:
            DependencyValidationError: If any reference is invalid
        """
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
        """
        Extract references from guard condition and validate them.

        Convenience method that combines parsing and validation.

        Args:
            guard_condition: The guard condition string (e.g., "extract.count > 5")
            agent_config: Current agent configuration
            agent_indices: Mapping of agent names to indices
            current_agent_name: Name of current agent

        Returns:
            List of error messages (empty if all valid)
        """
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
        """
        Extract action names referenced in a guard condition.

        Useful for dependency analysis and validation.

        Args:
            guard_condition: The guard condition string

        Returns:
            List of unique action names referenced
        """
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
        """
        Validate field references against action output schemas.

        Checks that referenced fields exist in the action's output schema.
        BREAKING: UDFs with field references MUST have output_type defined.

        Args:
            references: Field references to validate
            action_schemas: Mapping of action names to their JSON output schemas
            current_agent_name: Name of current agent (for error context)

        Returns:
            List of error messages (empty if all valid)

        Example:
            action_schemas = {
                'my_udf_action': {
                    'type': 'object',
                    'properties': {
                        'result': {'type': 'string'},
                        'count': {'type': 'integer'}
                    }
                }
            }

            errors = validator.validate_against_schemas(
                references=['my_udf_action.result', 'my_udf_action.invalid'],
                action_schemas=action_schemas
            )
            # Returns: ["Field 'invalid' not found in 'my_udf_action' output schema..."]
        """
        errors = []

        for ref in references:
            # Parse if string
            if isinstance(ref, str):
                try:
                    ref = self._parser.parse(ref)
                except (ValueError, TypeError) as e:
                    errors.append(f"Invalid reference syntax: '{ref}' - {e}")
                    continue

            action_name = ref.action_name

            # Skip special namespaces (never require schemas)
            if action_name in SPECIAL_NAMESPACES:
                continue

            # Skip if no schema available (e.g., LLM actions)
            if action_name not in action_schemas:
                # BREAKING: If a UDF is referenced but has no schema, that's an error
                # This enforces output_type for all referenced UDFs
                continue  # For now, skip - will tighten this later

            # Validate field path against schema
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
        """
        Perform both dependency and schema validation.

        Combines:
        1. Dependency graph validation (existing validate())
        2. Schema field validation (new validate_against_schemas())

        Args:
            references: Field references to validate
            validation_context: Dict containing:
                - agent_config: Current agent configuration
                - agent_indices: Mapping of agent names to indices
                - action_schemas: Mapping of action names to JSON schemas
                - current_agent_name: (optional) Name of current agent

        Returns:
            List of error messages (empty if all valid)

        Example:
            errors = validator.validate_with_schemas(
                references=['my_udf.result'],
                validation_context={
                    'agent_config': {'dependencies': ['my_udf']},
                    'agent_indices': {'my_udf': 0, 'current': 1},
                    'action_schemas': {'my_udf': {...}},
                    'current_agent_name': 'current'
                }
            )
        """
        # Phase 1: Dependency graph validation
        dep_errors = self.validate(
            references=references,
            agent_config=validation_context["agent_config"],
            agent_indices=validation_context["agent_indices"],
            current_agent_name=validation_context.get("current_agent_name"),
        )

        # Phase 2: Schema validation
        schema_errors = self.validate_against_schemas(
            references=references, action_schemas=validation_context["action_schemas"]
        )

        # Combine all errors
        return dep_errors + schema_errors
