from __future__ import annotations

"""Reprompt generation strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class RepromptContext:
    """Context for reprompt generation."""

    original_prompt: str
    validation_error: str
    validation_criteria: Dict
    attempt_number: int
    failed_response: Any
    agent_config: Dict


class RepromptStrategy(ABC):
    """Base class for reprompt generation strategies."""

    @abstractmethod
    def generate_improved_prompt(self, context: RepromptContext) -> str:
        """Generate an improved prompt based on validation failure."""


class LLMRepromptStrategy(RepromptStrategy):
    """Uses an LLM to generate improved prompts."""

    def __init__(self, llm_config: Dict):
        self.llm_config = llm_config
        self.include_previous_response = llm_config.get("include_previous_response", True)
        self.prompt_template = llm_config.get(
            "prompt_template", self._default_template()
        )

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        # Simple template-based construction - no LLM call needed
        base_prompt = (
            f"{context.original_prompt}\n\n"
            f"IMPORTANT: Previous attempt failed validation with error: {context.validation_error}. "
        )
        
        if self.include_previous_response:
            base_prompt += f"Your previous response was: \"{context.failed_response}\"\n"
        
        improved_prompt = base_prompt + "Reprocess and ensure your response meets the requirements."
        
        print(f"📝 CONSTRUCTED IMPROVED PROMPT:")
        print(f"=" * 80)
        print(improved_prompt)
        print(f"=" * 80)
        
        return improved_prompt

    def _default_template(self) -> str:
        return (
            "You are an expert prompt engineer. A previous LLM attempt failed validation.\n\n"
            "Original Prompt: {original_prompt}\n\n"
            "Validation Error: {validation_error}\n\n"
            "The prompt must meet these criteria: {validation_criteria}\n\n"
            "The LLM's failed response was: {failed_response}\n\n"
            "This is attempt #{attempt_number}.\n\n"
            "Generate an improved prompt that will help the LLM meet the validation criteria. "
            "Be specific and explicit about the requirements. Focus on clarity and constraints.\n\n"
            "Return ONLY the improved prompt, nothing else."
        )


class TemplateRepromptStrategy(RepromptStrategy):
    """Uses predefined templates for common failure patterns."""

    def __init__(self, templates: Dict[str, str]):
        self.templates = templates

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        for pattern, template in self.templates.items():
            if pattern in context.validation_error.lower():
                return template.format(
                    original_prompt=context.original_prompt,
                    **context.validation_criteria,
                )

        return f"{context.original_prompt}\n\nIMPORTANT: {context.validation_error}"
