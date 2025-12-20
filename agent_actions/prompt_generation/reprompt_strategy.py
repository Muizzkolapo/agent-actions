"""Strategies for generating improved prompts after validation failures."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class RepromptContext:
    """Context for generating an improved prompt."""
    original_prompt: str
    validation_error: str
    validation_criteria: Dict[str, Any]
    attempt_number: int
    failed_response: Any
    agent_config: Dict[str, Any]


# pylint: disable=too-few-public-methods
class RepromptStrategy(ABC):
    """Base class for reprompt generation strategies."""

    @abstractmethod
    def generate_improved_prompt(self, context: RepromptContext) -> str:
        """Generate an improved prompt based on the failure context."""


# pylint: disable=too-few-public-methods
class LLMRepromptStrategy(RepromptStrategy):
    """Strategy that uses templates to construct improved prompts."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.prompt_debug = config.get("prompt_debug", False)
        self.include_previous = config.get("include_previous_response", True)
        self.feedback_template = config.get(
            "feedback_template",
            "The previous response did not meet the requirements: {error}\n"
            "Please try again with the following criteria: {criteria}"
        )

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        """Generate improved prompt using template construction."""
        if self.prompt_debug:
            print("🤖 LLM REPROMPT STRATEGY:")
            print(f"   Attempt #{context.attempt_number}")
            print(f"   Error: {context.validation_error}")
            print(f"   Criteria: {context.validation_criteria}")

        # Build the improved prompt
        parts = []

        # Add original prompt
        parts.append(context.original_prompt)

        # Add feedback about the error
        feedback = self.feedback_template.format(
            error=context.validation_error,
            criteria=context.validation_criteria
        )
        parts.append(f"\n\n{feedback}")

        # Optionally include previous response
        if self.include_previous and context.failed_response:
            parts.append(f"\n\nYour previous response was: {context.failed_response}")

        # Add attempt number for context
        max_attempts = context.validation_criteria.get('max_attempts', 3)
        parts.append(f"\n\n(Attempt {context.attempt_number} of {max_attempts})")

        improved_prompt = "\n".join(parts)

        if self.prompt_debug:
            print(f"   Generated prompt: {improved_prompt[:200]}...")

        return improved_prompt


# pylint: disable=too-few-public-methods
class TemplateRepromptStrategy(RepromptStrategy):
    """Strategy that uses predefined templates for different error types."""

    def __init__(self, templates: Dict[str, str], prompt_debug: bool = False) -> None:
        self.templates = templates
        self.prompt_debug = prompt_debug
        self.default_template = templates.get(
            "default",
            "{original_prompt}\n\nThe response did not meet requirements: "
            "{error}\nPlease try again."
        )

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        """Generate improved prompt using specific templates."""
        if self.prompt_debug:
            print("📝 TEMPLATE REPROMPT STRATEGY:")
            print(f"   Looking for template for error: {context.validation_error}")

        # Find matching template based on error message
        template = self.default_template
        for error_pattern, tmpl in self.templates.items():
            if error_pattern != "default" and error_pattern in context.validation_error:
                template = tmpl
                if self.prompt_debug:
                    print(f"   Using template for: {error_pattern}")
                break

        # Format the template
        improved_prompt = template.format(
            original_prompt=context.original_prompt,
            error=context.validation_error,
            criteria=context.validation_criteria,
            attempt=context.attempt_number
        )

        if self.prompt_debug:
            print(f"   Generated prompt: {improved_prompt[:200]}...")

        return improved_prompt
