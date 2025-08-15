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
        self.prompt_debug: bool = False

    def configure(self, config: Dict) -> None:
        self.prompt_debug = config.get("prompt_debug", False)
        
        if self.prompt_debug:
            print(f"🔄 REPROMPT INTERCEPTOR CONFIGURE:")
            print(f"   Config received: {config}")
        
        strategy_type = config.get("strategy", "llm")
        self.max_attempts = config.get("max_attempts", 3)

        if self.prompt_debug:
            print(f"   Strategy type: {strategy_type}")
            print(f"   Max attempts: {self.max_attempts}")

        if strategy_type == "llm":
            # Note: "llm" strategy now uses template construction, not actual LLM calls
            llm_config = config.get("llm_config", {})
            llm_config["prompt_debug"] = self.prompt_debug
            if self.prompt_debug:
                print(f"   LLM config: {llm_config}")
            self.strategy = LLMRepromptStrategy(llm_config)
        elif strategy_type == "simple":
            # Simple strategy uses template construction with configurable options
            simple_config = {
                "include_previous_response": config.get("include_previous_response", True),
                "prompt_debug": self.prompt_debug
            }
            if self.prompt_debug:
                print(f"   Simple config: {simple_config}")
            self.strategy = LLMRepromptStrategy(simple_config)
        elif strategy_type == "template":
            self.strategy = TemplateRepromptStrategy(
                config.get("templates", {}),
                prompt_debug=self.prompt_debug
            )
        else:
            raise ValueError(f"Unknown reprompt strategy: {strategy_type}")
            
        if self.prompt_debug:
            print(f"   Created strategy: {type(self.strategy).__name__}")

    def intercept(self, response: Any, context: Dict) -> InterceptorResult:
        if self.prompt_debug:
            print(f"🧠 REPROMPT INTERCEPTOR INTERCEPT:")
            print(f"   Context keys: {list(context.keys())}")
            print(f"   Has validation_error: {'validation_error' in context}")
        
        if "validation_error" not in context:
            if self.prompt_debug:
                print(f"   ⚠️ No validation error - continuing")
            return InterceptorResult(continue_processing=True)

        attempt = context.get("attempt", 0)
        if self.prompt_debug:
            print(f"   Current attempt: {attempt}, Max attempts: {self.max_attempts}")
            print(f"   Check: {attempt} >= {self.max_attempts} = {attempt >= self.max_attempts}")
        
        if attempt >= self.max_attempts:
            if self.prompt_debug:
                print(f"   🛑 MAX ATTEMPTS REACHED - stopping")
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
