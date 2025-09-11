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
        self.prompt_debug = llm_config.get("prompt_debug", False)
        self.feedback_template = llm_config.get("feedback_template", None)
        self.prompt_template = llm_config.get(
            "prompt_template", self._default_template()
        )

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        # Use custom feedback template with focused correction if provided
        if self.feedback_template:
            try:
                template_vars = {
                    "validation_errors": context.validation_error,
                    "target_relationship": self._extract_target_relationship(context.validation_error),
                    "correct_answer_words": context.validation_criteria.get("correct_answer_words", "unknown")
                }
                
                feedback_section = self.feedback_template.format(**template_vars)
                
                # Research-based focused error correction approach
                # Instead of appending to original prompt, create focused correction
                improved_prompt = self._create_focused_correction_prompt(context, feedback_section)
                
                if self.prompt_debug:
                    print(f"📝 FOCUSED CORRECTION PROMPT USED:")
                    print(f"==" * 40)
                    print(improved_prompt)
                    print(f"==" * 40)
                    
                return improved_prompt
                
            except KeyError as e:
                if self.prompt_debug:
                    print(f"⚠️  Template variable missing: {e}")
                # Fallback to simple construction
        
        # Simple template-based construction - no LLM call needed
        base_prompt = (
            f"{context.original_prompt}\n\n"
            f"IMPORTANT: Previous attempt failed validation with error: {context.validation_error}. "
        )
        
        if self.include_previous_response:
            base_prompt += f"Your previous response was: \"{context.failed_response}\"\n"
        
        improved_prompt = base_prompt + "Reprocess and ensure your response meets the requirements."
        
        if self.prompt_debug:
            print(f"📝 CONSTRUCTED IMPROVED PROMPT:")
            print(f"=" * 80)
            print(improved_prompt)
            print(f"=" * 80)
        
        return improved_prompt

    def _extract_target_relationship(self, validation_error: str) -> str:
        """Extract target relationship from validation error message."""
        if "LONGER" in validation_error or "greater_than" in validation_error:
            return "longer than"
        elif "SHORTER" in validation_error or "lesser_than" in validation_error:
            return "shorter than"
        elif "SIMILAR" in validation_error or "equal_to" in validation_error:
            return "similar length to"
        else:
            return "different from"
    
    def _create_focused_correction_prompt(self, context: RepromptContext, feedback_section: str) -> str:
        """Create a focused correction prompt based on research best practices."""
        
        # Extract key context elements
        correct_answer_words = context.validation_criteria.get("correct_answer_words", "unknown")
        target_relationship = self._extract_target_relationship(context.validation_error)
        
        # Research shows 3 examples are optimal - create focused few-shot correction
        focused_prompt = f"""TASK: Generate a distractor that is {target_relationship} the correct answer ({correct_answer_words} words).

ERROR ANALYSIS:
{feedback_section}

CORRECTION EXAMPLES:
INPUT: "Wrong answer" (2 words) - TOO SHORT for 8-word correct answer
OUTPUT: "Wrong answer with additional explanatory context and detail" (9 words)

INPUT: "Very detailed wrong answer with excessive explanatory content that goes on too long" (14 words) - TOO LONG for 8-word correct answer  
OUTPUT: "Concise wrong answer explanation" (4 words)

YOUR CURRENT ATTEMPT:
{context.failed_response}

GENERATE CORRECTED VERSION:
- Maintain the incorrectness and plausibility
- Adjust word count to be {target_relationship} {correct_answer_words} words
- Keep the same technical accuracy level
- Output only the corrected distractor, nothing else"""

        return focused_prompt

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

    def __init__(self, templates: Dict[str, str], prompt_debug: bool = False):
        self.templates = templates
        self.prompt_debug = prompt_debug

    def generate_improved_prompt(self, context: RepromptContext) -> str:
        for pattern, template in self.templates.items():
            if pattern in context.validation_error.lower():
                improved_prompt = template.format(
                    original_prompt=context.original_prompt,
                    **context.validation_criteria,
                )
                if self.prompt_debug:
                    print(f"📝 TEMPLATE MATCH FOUND:")
                    print(f"   Pattern: {pattern}")
                    print(f"   Template used: {template[:50]}...")
                return improved_prompt

        # Default fallback
        improved_prompt = f"{context.original_prompt}\n\nIMPORTANT: {context.validation_error}"
        if self.prompt_debug:
            print(f"📝 NO TEMPLATE MATCH - Using default fallback")
        return improved_prompt
