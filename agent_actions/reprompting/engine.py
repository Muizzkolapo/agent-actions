"""
Core reprompt engine that orchestrates JSON repair, constraints, and prompt improvement.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_actions.reprompting.config import RepromptConfig
from agent_actions.reprompting.constraints import ConstraintValidator
from agent_actions.reprompting.json_repair import JSONRepairStrategy, RepairResult


@dataclass
class RepromptResult:
    """Result of reprompt processing.

    Attributes:
        success: Whether the response is valid (no reprompt needed)
        response: The (possibly repaired) response
        needs_retry: Whether a retry is needed
        improved_prompt: New prompt for retry (if needs_retry)
        attempt: Current attempt number
        error: Error message if validation failed
        repair_method: JSON repair method used (if any)
        constraint_failed: Name of failed constraint (if any)
    """

    success: bool
    response: Any = None
    needs_retry: bool = False
    improved_prompt: Optional[str] = None
    attempt: int = 0
    error: Optional[str] = None
    repair_method: Optional[str] = None
    constraint_failed: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# Error-specific prompt templates
ERROR_TEMPLATES: Dict[str, str] = {
    "json_parse_failure": """
Your previous response could not be parsed as valid JSON.

Error: {error}

Please respond with ONLY valid JSON. Do not include:
- Markdown code blocks (no ```)
- Explanatory text before or after the JSON
- Comments

Your response should start with {{ or [ and end with }} or ].
""",
    "missing_fields": """
Your previous response is missing required fields.

Missing: {error}

Please include ALL required fields in your response.
""",
    "constraint_violation": """
Your previous response did not meet the requirements.

Issue: {error}

Please correct this and try again.
""",
    "empty_fields": """
Your previous response has empty fields that should contain values.

Empty fields: {error}

Please provide values for all required fields.
""",
    "type_mismatch": """
Your previous response has fields with incorrect types.

{error}

Please ensure field types match the expected schema.
""",
    "default": """
Your previous response did not meet the requirements.

Issue: {error}

Please try again, ensuring your response is valid and complete.
""",
}


def _select_template(error: str, constraint_name: Optional[str] = None) -> str:
    """Select appropriate error template based on error type."""
    if "JSON" in error or "parse" in error.lower():
        return ERROR_TEMPLATES["json_parse_failure"]
    if constraint_name == "required_fields" or "Missing" in error:
        return ERROR_TEMPLATES["missing_fields"]
    if constraint_name == "non_empty" or "empty" in error.lower():
        return ERROR_TEMPLATES["empty_fields"]
    if constraint_name == "field_types" or "type" in error.lower():
        return ERROR_TEMPLATES["type_mismatch"]
    if constraint_name:
        return ERROR_TEMPLATES["constraint_violation"]
    return ERROR_TEMPLATES["default"]


class RepromptEngine:
    """Core reprompt logic that orchestrates repair, validation, and prompt improvement.

    The engine processes responses through this pipeline:
    1. If JSON mode: attempt JSON repair (no API call needed)
    2. Run constraint validation
    3. If validation fails: generate improved prompt for retry

    Usage:
        config = RepromptConfig.from_yaml("smart")
        engine = RepromptEngine(config, constraints=[{"not_contains": "maze"}])

        result = engine.process_response(
            response=raw_response,
            context={"original_prompt": "...", "attempt": 1}
        )

        if result.needs_retry:
            # Use result.improved_prompt for next attempt
            pass
    """

    def __init__(
        self,
        config: RepromptConfig,
        constraints: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Initialize the reprompt engine.

        Args:
            config: RepromptConfig instance
            constraints: List of constraint configurations
        """
        self.config = config
        self.constraints = constraints or config.constraints or []
        self.json_repair = JSONRepairStrategy()
        self.constraint_validator = ConstraintValidator()

    def process_response(
        self,
        response: Any,
        context: Dict[str, Any],
    ) -> RepromptResult:
        """Process a response through repair and validation.

        Args:
            response: The raw LLM response
            context: Context dict with:
                - original_prompt: The original prompt
                - attempt: Current attempt number (0-indexed)
                - json_mode: Whether JSON output is expected

        Returns:
            RepromptResult indicating success or retry needed
        """
        attempt = context.get("attempt", 0)
        original_prompt = context.get("original_prompt", "")
        json_mode = context.get("json_mode", False)

        # Check if we've exceeded max attempts
        if attempt >= self.config.max_attempts:
            return RepromptResult(
                success=False,
                response=response,
                needs_retry=False,
                error="Maximum reprompt attempts reached",
                attempt=attempt,
                metadata={"max_attempts_reached": True},
            )

        # Step 1: JSON repair if enabled and in JSON mode
        repaired_response = response
        repair_method = None

        if self.config.json_repair and json_mode:
            repair_result = self._try_json_repair(response)
            if repair_result.success:
                repaired_response = repair_result.data
                repair_method = repair_result.repair_method
            elif repair_result.error:
                # JSON repair failed - need to reprompt
                improved_prompt = self.generate_improved_prompt(
                    original_prompt=original_prompt,
                    error=repair_result.error,
                    attempt=attempt + 1,
                    constraint_name=None,
                )
                return RepromptResult(
                    success=False,
                    response=response,
                    needs_retry=True,
                    improved_prompt=improved_prompt,
                    attempt=attempt + 1,
                    error=repair_result.error,
                    repair_method=None,
                )

        # Step 2: Run constraints
        if self.constraints:
            constraint_result = self.constraint_validator.validate(
                repaired_response, self.constraints
            )
            if not constraint_result.passed:
                improved_prompt = self.generate_improved_prompt(
                    original_prompt=original_prompt,
                    error=constraint_result.error or "Constraint validation failed",
                    attempt=attempt + 1,
                    constraint_name=constraint_result.constraint_name,
                )
                return RepromptResult(
                    success=False,
                    response=repaired_response,
                    needs_retry=True,
                    improved_prompt=improved_prompt,
                    attempt=attempt + 1,
                    error=constraint_result.error,
                    repair_method=repair_method,
                    constraint_failed=constraint_result.constraint_name,
                )

        # All validations passed
        return RepromptResult(
            success=True,
            response=repaired_response,
            needs_retry=False,
            attempt=attempt,
            repair_method=repair_method,
        )

    def _try_json_repair(self, response: Any) -> RepairResult:
        """Attempt to repair JSON if response is a string."""
        # Check if this is an error response from a provider client (dict)
        if isinstance(response, dict) and "raw_response" in response and "_parse_error" in response:
            # Extract raw content for repair
            raw_content = response["raw_response"]
            if isinstance(raw_content, str):
                return self.json_repair.attempt_repair(raw_content)
            # If raw_response is not a string, treat as already parsed
            return RepairResult(success=True, data=raw_content, repair_method="already_parsed")

        # Check if this is a list containing a single error dict (common from providers)
        if isinstance(response, list) and len(response) == 1:
            item = response[0]
            if isinstance(item, dict) and "raw_response" in item and "_parse_error" in item:
                # Extract and repair, then wrap back in list
                raw_content = item["raw_response"]
                if isinstance(raw_content, str):
                    repair_result = self.json_repair.attempt_repair(raw_content)
                    if repair_result.success:
                        # Wrap repaired data back in list to match input structure
                        return RepairResult(
                            success=True,
                            data=[repair_result.data],
                            repair_method=repair_result.repair_method,
                        )
                    return repair_result
                # If raw_response is not a string, wrap as list
                return RepairResult(
                    success=True, data=[raw_content], repair_method="already_parsed"
                )

        if isinstance(response, (dict, list)):
            # Already parsed JSON
            return RepairResult(success=True, data=response, repair_method="already_parsed")

        if isinstance(response, str):
            return self.json_repair.attempt_repair(response)

        # Not a string or dict/list - convert to string and try
        try:
            text = str(response)
            return self.json_repair.attempt_repair(text)
        except Exception as e:
            return RepairResult(success=False, error=str(e))

    def generate_improved_prompt(
        self,
        original_prompt: str,
        error: str,
        attempt: int,
        constraint_name: Optional[str] = None,
    ) -> str:
        """Generate an improved prompt based on the failure.

        Args:
            original_prompt: The original prompt that was sent
            error: Error message describing what failed
            attempt: Current attempt number (1-indexed)
            constraint_name: Name of failed constraint (if any)

        Returns:
            Improved prompt for retry
        """
        # Select appropriate template
        template = _select_template(error, constraint_name)

        # Format error feedback
        feedback = template.format(error=error)

        # Build improved prompt
        parts = [
            original_prompt,
            "",
            "---",
            f"CORRECTION NEEDED (Attempt {attempt} of {self.config.max_attempts}):",
            feedback.strip(),
            "---",
            "",
            "Please provide a corrected response:",
        ]

        return "\n".join(parts)

    def should_use_critique(self, attempt: int) -> bool:
        """Check if LLM critique should be used for this attempt."""
        return self.config.should_use_critique(attempt)

    def should_use_reflection(self, attempt: int) -> bool:
        """Check if self-reflection should be used for this attempt."""
        return self.config.should_use_reflection(attempt)
