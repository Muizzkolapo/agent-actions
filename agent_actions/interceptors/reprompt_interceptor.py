from __future__ import annotations

"""Interceptor that generates improved prompts on validation failure."""

from typing import Any, Dict

from .base import InterceptorResult, ResponseInterceptor
from ..strategies.reprompt_strategy import (
    LLMRepromptStrategy,
    RepromptContext,
    RepromptStrategy,
    TemplateRepromptStrategy,
)


class RepromptInterceptor(ResponseInterceptor):
    """Interceptor that generates improved prompts on validation failure."""

    def __init__(self) -> None:
        self.strategy: RepromptStrategy | None = None
        self.max_attempts: int = 3

    def configure(self, config: Dict) -> None:
        strategy_type = config.get("strategy", "llm")
        self.max_attempts = config.get("max_attempts", 3)

        if strategy_type == "llm":
            self.strategy = LLMRepromptStrategy(config.get("llm_config", {}))
        elif strategy_type == "template":
            self.strategy = TemplateRepromptStrategy(config.get("templates", {}))
        else:
            raise ValueError(f"Unknown reprompt strategy: {strategy_type}")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        if "validation_error" not in context:
            return InterceptorResult(continue_processing=True)

        attempt = context.get("attempt", 0)
        if attempt >= self.max_attempts:
            return InterceptorResult(
                continue_processing=False,
                metadata={"max_attempts_reached": True},
            )

        reprompt_context = RepromptContext(
            original_prompt=context.get("original_prompt", context.get("prompt")),
            validation_error=context["validation_error"],
            validation_criteria=context.get("validator_args", {}),
            attempt_number=attempt + 1,
            failed_response=context.get("failed_response"),
            agent_config=context.get("agent_config", {}),
        )

        if not self.strategy:
            raise ValueError("Reprompt strategy not configured")

        improved_prompt = self.strategy.generate_improved_prompt(reprompt_context)

        return InterceptorResult(
            continue_processing=False,
            retry_context={
                "prompt": improved_prompt,
                "original_prompt": reprompt_context.original_prompt,
                "attempt": attempt + 1,
                "history": context.get("history", [])
                + [
                    {
                        "attempt": attempt,
                        "prompt": context.get("prompt"),
                        "error": context["validation_error"],
                    }
                ],
            },
        )
