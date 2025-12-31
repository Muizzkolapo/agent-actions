"""Template variable validator for pre-flight validation.

Extracts variables from Jinja2 templates and validates they exist in context,
without actually rendering the template. This catches missing variable errors
early, before any LLM calls are made.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from jinja2 import Environment, meta, TemplateSyntaxError

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)


class TemplateVariableValidator(BaseValidator):
    """Validates that Jinja2 template variables exist in the provided context.

    This validator parses Jinja2 templates to extract all referenced variables,
    then checks if those variables are available in the context. This allows
    catching missing variable errors before template rendering.

    Attributes:
        issues: List of ValidationIssue objects found during validation
    """

    def __init__(self) -> None:
        super().__init__()
        self.issues: List[ValidationIssue] = []
        self._env = Environment()

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Validate template variables against provided context.

        Args:
            data: Dictionary containing:
                - 'template': The Jinja2 template string
                - 'context': The context dict with available variables
            config: Optional config with:
                - 'agent_name': Name of the agent for error messages
                - 'strict': If True, any undefined variable is an error
                - 'ignore_builtins': If True, ignore Jinja2 builtin functions

        Returns:
            bool: True if all template variables are available, False otherwise
        """
        self.clear_errors()
        self.clear_warnings()
        self.issues = []

        if not isinstance(data, dict):
            self.add_error(
                "Validation data must be a dictionary with 'template' and 'context' keys."
            )
            return False

        template = data.get("template")
        context = data.get("context", {})
        config = config or {}

        if template is None:
            self.add_error("No template provided for validation.")
            return False

        agent_name = config.get("agent_name")
        strict = config.get("strict", True)
        ignore_builtins = config.get("ignore_builtins", True)

        # Extract variables from template
        try:
            template_vars, parse_errors = self._extract_template_variables(
                template, ignore_builtins
            )
        except TemplateSyntaxError as e:
            self.add_error(f"Template syntax error at line {e.lineno}: {e.message}")
            self.issues.append(
                ValidationIssue(
                    message=f"Template syntax error: {e.message}",
                    issue_type="error",
                    category="template",
                    agent_name=agent_name,
                    location=f"line {e.lineno}" if e.lineno else None,
                )
            )
            return False

        # Add any parse errors/warnings
        for error in parse_errors:
            self.add_warning(error)

        # Get available context keys (flatten nested structures)
        available_vars = self._get_available_variables(context)

        # Find missing variables
        missing_vars = self._find_missing_variables(template_vars, available_vars)

        if missing_vars:
            # Determine severity
            if strict:
                for var in missing_vars:
                    self.add_error(f"Template references undefined variable: {var}")

                self.issues.append(
                    PreFlightErrorFormatter.create_template_variable_issue(
                        missing_variables=list(missing_vars),
                        available_variables=list(available_vars),
                        agent_name=agent_name,
                    )
                )
            else:
                for var in missing_vars:
                    self.add_warning(f"Template references potentially undefined variable: {var}")

        return not self.has_errors()

    def validate_template_string(
        self,
        template: str,
        context: Dict[str, Any],
        agent_name: Optional[str] = None,
    ) -> Tuple[bool, List[str], List[str]]:
        """Convenience method to validate a template string.

        Args:
            template: The Jinja2 template string
            context: The context dict with available variables
            agent_name: Optional agent name for error messages

        Returns:
            Tuple of (is_valid, list of missing vars, list of available vars)
        """
        data = {"template": template, "context": context}
        config = {"agent_name": agent_name, "strict": True}

        is_valid = self.validate(data, config)

        # Extract missing and available from issues
        missing = []
        available = []
        if self.issues:
            for issue in self.issues:
                missing.extend(issue.missing_refs)
                available = issue.available_refs

        return is_valid, missing, available

    def _extract_template_variables(
        self, template: str, ignore_builtins: bool = True
    ) -> Tuple[Set[str], List[str]]:
        """Extract all variable references from a Jinja2 template.

        Uses Jinja2's AST parser to find all undeclared variables.
        This properly handles loop variables ({% for ref in items %})
        by only returning variables that are actually undefined.

        Args:
            template: The Jinja2 template string
            ignore_builtins: If True, filter out Jinja2 builtin functions

        Returns:
            Tuple of (set of variable names, list of parse warnings)
        """
        warnings = []

        # Parse the template into an AST
        ast = self._env.parse(template)

        # Find all undeclared variables - this properly excludes:
        # - Loop variables ({% for ref in items %} - 'ref' is not returned)
        # - Set variables ({% set x = 1 %} - 'x' is not returned)
        # - Macro parameters
        variables = meta.find_undeclared_variables(ast)

        if ignore_builtins:
            # Filter out common Jinja2 builtins
            builtins = {
                "range",
                "dict",
                "lipsum",
                "cycler",
                "joiner",
                "namespace",
                "loop",
                "self",
                "super",
                "true",
                "false",
                "none",
            }
            variables = variables - builtins

        return variables, warnings

    def _get_available_variables(self, context: Dict[str, Any]) -> Set[str]:
        """Get all available variable names from context.

        Flattens nested dictionaries to get all possible access paths.

        Args:
            context: The context dictionary

        Returns:
            Set of available variable names
        """
        available = set()

        def _add_keys(d: Dict[str, Any], prefix: str = "") -> None:
            for key, value in d.items():
                full_key = f"{prefix}.{key}" if prefix else key
                available.add(key)  # Add the key itself
                if prefix:
                    available.add(full_key)  # Add full path
                if isinstance(value, dict):
                    _add_keys(value, key)

        if isinstance(context, dict):
            _add_keys(context)

        return available

    def _find_missing_variables(
        self, template_vars: Set[str], available_vars: Set[str]
    ) -> Set[str]:
        """Find variables referenced in template but not in context.

        Args:
            template_vars: Variables referenced in the template
            available_vars: Variables available in context

        Returns:
            Set of missing variable names
        """
        missing = set()

        for var in template_vars:
            # Check if var or its root (for nested access) is available
            root_var = var.split(".")[0]
            if root_var not in available_vars and var not in available_vars:
                missing.add(var)

        return missing

    def get_issues(self) -> List[ValidationIssue]:
        """Get the list of validation issues found.

        Returns:
            List of ValidationIssue objects
        """
        return self.issues
