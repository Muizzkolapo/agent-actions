"""Pre-flight validation orchestrator.

Coordinates all pre-flight validators to run before any LLM calls,
providing a unified validation entry point for both batch and online modes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)
from agent_actions.validation.preflight.template_variable_validator import (
    TemplateVariableValidator,
)
from agent_actions.validation.preflight.context_structure_validator import (
    ContextStructureValidator,
)


@dataclass
class PreFlightValidationResult:
    """Result of pre-flight validation.

    Attributes:
        is_valid: True if validation passed with no errors
        errors: List of error issues found
        warnings: List of warning issues found
        mode: Execution mode ('batch' or 'online')
        agent_name: Name of the agent validated
    """

    is_valid: bool
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    mode: str = "unknown"
    agent_name: Optional[str] = None

    def format_message(self) -> str:
        """Format the validation result as a user-friendly message.

        Returns:
            Formatted message string
        """
        all_issues = self.errors + self.warnings
        return PreFlightErrorFormatter.format_issues(all_issues, self.mode)

    def raise_if_invalid(self) -> None:
        """Raise PreFlightValidationError if validation failed.

        Raises:
            PreFlightValidationError: If there are any errors
        """
        if not self.is_valid and self.errors:
            # Use the first error for the main message
            first_error = self.errors[0]
            raise PreFlightValidationError(
                first_error.message,
                available_references=first_error.available_refs,
                missing_references=first_error.missing_refs,
                hint=first_error.hint,
                mode=self.mode,
                agent_name=self.agent_name,
                context={
                    "total_errors": len(self.errors),
                    "total_warnings": len(self.warnings),
                    "all_issues": [
                        {"message": e.message, "category": e.category} for e in self.errors
                    ],
                },
            )


class PreFlightValidator:
    """Orchestrates pre-flight validation for both batch and online modes.

    This class coordinates multiple validators to run before any LLM calls,
    ensuring consistent validation and error messaging across execution modes.

    Example:
        validator = PreFlightValidator()
        result = validator.validate(
            template="{{ action.field }}",
            context={"action": {"other_field": "value"}},
            agent_name="my_agent",
            mode="online"
        )
        if not result.is_valid:
            print(result.format_message())
            result.raise_if_invalid()
    """

    def __init__(self) -> None:
        self._template_validator = TemplateVariableValidator()
        self._context_validator = ContextStructureValidator()

    def validate(
        self,
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
        mode: str = "unknown",
        expected_fields: Optional[List[str]] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> PreFlightValidationResult:
        """Run all pre-flight validations.

        Args:
            template: Optional Jinja2 template string to validate
            context: The context data available for template rendering
            agent_name: Name of the agent being validated
            mode: Execution mode ('batch' or 'online')
            expected_fields: Optional list of required context fields
            agent_config: Optional agent configuration for additional validation

        Returns:
            PreFlightValidationResult with validation status and issues
        """
        all_errors: List[ValidationIssue] = []
        all_warnings: List[ValidationIssue] = []

        # 1. Validate template variables if template provided
        if template is not None and context is not None:
            template_issues = self._validate_template(template, context, agent_name)
            for issue in template_issues:
                if issue.issue_type == "error":
                    all_errors.append(issue)
                else:
                    all_warnings.append(issue)

        # 2. Validate context structure if expected fields provided
        if context is not None and expected_fields:
            context_issues = self._validate_context_structure(context, expected_fields, agent_name)
            for issue in context_issues:
                if issue.issue_type == "error":
                    all_errors.append(issue)
                else:
                    all_warnings.append(issue)

        # 3. Validate agent config if provided
        if agent_config is not None:
            config_issues = self._validate_agent_config(agent_config, agent_name)
            for issue in config_issues:
                if issue.issue_type == "error":
                    all_errors.append(issue)
                else:
                    all_warnings.append(issue)

        is_valid = len(all_errors) == 0

        return PreFlightValidationResult(
            is_valid=is_valid,
            errors=all_errors,
            warnings=all_warnings,
            mode=mode,
            agent_name=agent_name,
        )

    def validate_for_batch(
        self,
        template: Optional[str],
        context: Dict[str, Any],
        agent_name: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> PreFlightValidationResult:
        """Convenience method for batch mode validation.

        Args:
            template: Jinja2 template string
            context: Context data for template rendering
            agent_name: Name of the agent
            agent_config: Optional agent configuration

        Returns:
            PreFlightValidationResult
        """
        return self.validate(
            template=template,
            context=context,
            agent_name=agent_name,
            mode="batch",
            agent_config=agent_config,
        )

    def validate_for_online(
        self,
        template: Optional[str],
        context: Dict[str, Any],
        agent_name: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> PreFlightValidationResult:
        """Convenience method for online mode validation.

        Args:
            template: Jinja2 template string
            context: Context data for template rendering
            agent_name: Name of the agent
            agent_config: Optional agent configuration

        Returns:
            PreFlightValidationResult
        """
        return self.validate(
            template=template,
            context=context,
            agent_name=agent_name,
            mode="online",
            agent_config=agent_config,
        )

    def _validate_template(
        self,
        template: str,
        context: Dict[str, Any],
        agent_name: Optional[str],
    ) -> List[ValidationIssue]:
        """Validate template variables against context.

        Args:
            template: The template string
            context: Available context data
            agent_name: Name of the agent

        Returns:
            List of validation issues
        """
        data = {"template": template, "context": context}
        config = {"agent_name": agent_name, "strict": True}

        self._template_validator.validate(data, config)
        return self._template_validator.get_issues()

    def _validate_context_structure(
        self,
        context: Dict[str, Any],
        expected_fields: List[str],
        agent_name: Optional[str],
    ) -> List[ValidationIssue]:
        """Validate context has required structure.

        Args:
            context: The context data
            expected_fields: Required field names
            agent_name: Name of the agent

        Returns:
            List of validation issues
        """
        data = {
            "context": context,
            "expected_fields": expected_fields,
        }
        config = {"agent_name": agent_name}

        self._context_validator.validate(data, config)
        return self._context_validator.get_issues()

    def _validate_agent_config(
        self,
        agent_config: Dict[str, Any],
        agent_name: Optional[str],
    ) -> List[ValidationIssue]:
        """Validate agent configuration basics.

        Args:
            agent_config: The agent configuration dict
            agent_name: Name of the agent

        Returns:
            List of validation issues
        """
        issues = []

        # Check for required config fields
        if agent_config is None:
            issues.append(
                ValidationIssue(
                    message="Agent configuration is None",
                    issue_type="error",
                    category="config",
                    hint="Ensure agent is properly defined in workflow configuration.",
                    agent_name=agent_name,
                )
            )
            return issues

        # Check for model_vendor if not a tool-type agent
        agent_type = agent_config.get("agent_type", "")
        if agent_type != "tool":
            if not agent_config.get("model_vendor"):
                issues.append(
                    ValidationIssue(
                        message="Missing model_vendor in agent configuration",
                        issue_type="error",
                        category="config",
                        missing_refs=["model_vendor"],
                        hint="Specify model_vendor (openai, anthropic, gemini) in agent config.",
                        agent_name=agent_name,
                    )
                )

        return issues


def validate_preflight(
    template: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    agent_name: Optional[str] = None,
    mode: str = "unknown",
    raise_on_error: bool = True,
) -> PreFlightValidationResult:
    """Convenience function for quick pre-flight validation.

    Args:
        template: Optional Jinja2 template string
        context: Optional context data
        agent_name: Name of the agent
        mode: Execution mode ('batch' or 'online')
        raise_on_error: If True, raise exception on validation failure

    Returns:
        PreFlightValidationResult

    Raises:
        PreFlightValidationError: If validation fails and raise_on_error is True
    """
    validator = PreFlightValidator()
    result = validator.validate(
        template=template,
        context=context,
        agent_name=agent_name,
        mode=mode,
    )

    if raise_on_error:
        result.raise_if_invalid()

    return result
