"""
Input Signature Validation for Agent Prompts.

This module validates that field references in agent prompts (like {agent.field})
match the actual fields available in the agent's LLM context.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from agent_actions.preprocessing.prompt_utils import PromptUtils
from agent_actions.validation.llm_context_utils import LLMContextUtils

@dataclass
class FieldValidationResult:
    """Result of validating a single field reference."""
    field_reference: str
    agent_name: str
    field_name: str
    is_valid: bool
    message: str
    help_text: Optional[str] = None

@dataclass
class ValidationResult:
    """Result of validating all field references in an agent's prompt."""
    agent_name: str
    errors: List[FieldValidationResult] = field(default_factory=list)
    warnings: List[FieldValidationResult] = field(default_factory=list)
    successes: List[FieldValidationResult] = field(default_factory=list)

    def has_errors(self) -> bool:
        """Check if validation found any errors."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if validation found any warnings."""
        return len(self.warnings) > 0

    def is_valid(self) -> bool:
        """Check if validation passed (no errors)."""
        return not self.has_errors()

class InputSignatureValidator:
    """
    Validates that field references in agent prompts match available LLM context.

    This validator ensures that when an agent references fields from dependencies
    (like {extractor.summary}), those fields will actually be available in the
    next agent's LLM context.
    """

    @staticmethod
    def validate_agent_inputs(agent_config: Dict[str, Any], dependency_configs: Dict[str, Dict[str, Any]], agent_name: str='unknown_agent') -> ValidationResult:
        """
        Validate that all field references in agent prompt are available.

        Args:
            agent_config: Configuration of the agent being validated
            dependency_configs: Dict mapping dependency names to their configs
            agent_name: Name of the agent being validated (for error messages)

        Returns:
            ValidationResult with errors, warnings, and successes

        Example:
            >>> agent_config = {
            ...     'prompt': 'Analyze {extractor.summary}',
            ...     'dependencies': ['extractor']
            ... }
            >>> dep_configs = {
            ...     'extractor': {
            ...         'output_schema': {'properties': {'summary': {}}},
            ...         'observe': [],
            ...         'drops': []
            ...     }
            ... }
            >>> result = InputSignatureValidator.validate_agent_inputs(
            ...     agent_config, dep_configs, 'analyzer'
            ... )
            >>> result.is_valid()
            True
        """
        result = ValidationResult(agent_name=agent_name)
        prompt = agent_config.get('prompt', '')
        if not prompt:
            return result
        references = PromptUtils.parse_field_references(prompt)
        if not references:
            return result
        declared_deps = set(agent_config.get('dependencies', []))
        if 'depends_on' in agent_config:
            declared_deps.update(agent_config['depends_on'])
        for ref in references:
            ref_agent = ref['reference']
            field_path = ref['field_path']
            full_ref = ref['full_match']
            if ref_agent in ('source', 'loop', 'workflow'):
                result.successes.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name='.'.join(field_path), is_valid=True, message=f"Special reference '{ref_agent}' is always available"))
                continue
            first_field = field_path[0] if field_path else None
            if not first_field:
                result.errors.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name='', is_valid=False, message=f'Invalid reference: {full_ref} has no field path', help_text='Field reference must be in format {agent.field}'))
                continue
            if ref_agent not in declared_deps:
                available = sorted(declared_deps) if declared_deps else []
                result.errors.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name=first_field, is_valid=False, message=f"Agent '{ref_agent}' not in dependencies", help_text=f"Add '{ref_agent}' to dependencies list. Available dependencies: {available}"))
                continue
            dep_config = dependency_configs.get(ref_agent)
            if not dep_config:
                result.errors.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name=first_field, is_valid=False, message=f"Configuration not found for dependency '{ref_agent}'", help_text='Ensure dependency config is provided in dependency_configs'))
                continue
            llm_context = LLMContextUtils.compute_llm_context(dep_config)
            if first_field not in llm_context:
                available_fields = sorted(llm_context) if llm_context else []
                result.errors.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name=first_field, is_valid=False, message=f"Field '{first_field}' not available in '{ref_agent}' output", help_text=f"Available fields from '{ref_agent}': {available_fields}"))
                continue
            result.successes.append(FieldValidationResult(field_reference=full_ref, agent_name=ref_agent, field_name=first_field, is_valid=True, message=f"Field '{first_field}' is available from '{ref_agent}'"))
        return result

    @staticmethod
    def format_validation_errors(validation_result: ValidationResult) -> str:
        """
        Format validation errors as a human-readable string.

        Args:
            validation_result: ValidationResult to format

        Returns:
            Formatted error message string
        """
        if not validation_result.has_errors():
            return ''
        lines = [f"Validation errors in agent '{validation_result.agent_name}':"]
        for error in validation_result.errors:
            lines.append(f'  - {error.field_reference}: {error.message}')
            if error.help_text:
                lines.append(f'    → {error.help_text}')
        return '\n'.join(lines)