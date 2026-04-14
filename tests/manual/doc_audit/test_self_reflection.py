#!/usr/bin/env python3
"""Manual smoke test: self-reflection feedback strategy.

Runs the reprompt loop with a fake LLM and PRINTS the retry prompts
so a human can inspect what the model would actually see — with and
without self-reflection enabled.

Run:
    python tests/manual/doc_audit/test_self_reflection.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# --- path fixup for standalone execution ---
if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from agent_actions.processing.recovery.reprompt import RepromptService
from agent_actions.processing.recovery.response_validator import self_reflection_strategy
from agent_actions.processing.recovery.validation import (
    _VALIDATION_REGISTRY,
    reprompt_validation,
)

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"
RULE = "─" * 72


def _header(title: str) -> None:
    print(f"\n{CYAN}{'═' * 72}")
    print(f"  {title}")
    print(f"{'═' * 72}{RESET}\n")


def _label(text: str) -> None:
    print(f"{YELLOW}  ▸ {text}{RESET}")


def _show_prompt(prompt: str) -> None:
    """Print a prompt with indentation so structure is visible."""
    for line in prompt.splitlines():
        print(f"  {DIM}│{RESET} {line}")
    print(f"  {DIM}│{RESET}")


def _run_scenario(title: str, use_reflection: bool) -> list[str]:
    """Run reprompt loop, return all prompts sent to the fake LLM."""
    _VALIDATION_REGISTRY.clear()

    @reprompt_validation("Response must contain a 'entities' list with at least one item")
    def check_entities(response: dict) -> bool:
        entities = response.get("entities")
        return isinstance(entities, list) and len(entities) > 0

    prompts: list[str] = []
    call_count = 0

    def fake_llm(prompt: str):
        nonlocal call_count
        prompts.append(prompt)
        call_count += 1
        if call_count <= 2:
            # Fail: missing entities field, then empty list
            if call_count == 1:
                return {"text": "Acme Corp signed a deal"}, True
            return {"entities": []}, True
        # Succeed on attempt 3
        return {"entities": [{"name": "Acme Corp", "type": "organization"}]}, True

    strategies = [self_reflection_strategy] if use_reflection else []

    service = RepromptService(
        validation_name="check_entities",
        max_attempts=4,
        strategies=strategies,
    )

    _header(title)
    result = service.execute(fake_llm, "Extract all entities from the following text.")

    for i, prompt in enumerate(prompts):
        attempt_num = i + 1
        is_retry = attempt_num > 1
        label = f"Attempt {attempt_num}" + (" (retry)" if is_retry else " (initial)")
        _label(label)
        _show_prompt(prompt)

    status = f"{GREEN}PASSED{RESET}" if result.passed else f"\033[31mFAILED{RESET}"
    print(f"  Result: {status} after {result.attempts} attempts")
    return prompts


def main() -> int:
    print(f"\n{CYAN}Self-Reflection Smoke Test{RESET}")
    print(f"{DIM}Inspect the retry prompts below. The reflection-enabled version")
    print(f"should include analysis instructions that help the model reason{RESET}")
    print(f"{DIM}about its failure before retrying.{RESET}")

    # --- Scenario 1: WITHOUT reflection ---
    prompts_without = _run_scenario(
        "SCENARIO 1: Reprompt WITHOUT self-reflection", use_reflection=False
    )

    # --- Scenario 2: WITH reflection ---
    prompts_with = _run_scenario("SCENARIO 2: Reprompt WITH self-reflection", use_reflection=True)

    # --- Comparison ---
    _header("COMPARISON: Retry prompt #2 (after first failure)")

    _label("WITHOUT reflection — prompt length")
    print(f"    {len(prompts_without[1])} chars\n")

    _label("WITH reflection — prompt length")
    print(f"    {len(prompts_with[1])} chars")
    print(f"    (+{len(prompts_with[1]) - len(prompts_without[1])} chars from reflection)\n")

    _label("Added text (reflection block)")
    # Show what reflection adds
    extra = prompts_with[1][len(prompts_without[1]) :]
    if extra.strip():
        for line in extra.strip().splitlines():
            print(f"    {GREEN}{line}{RESET}")
    else:
        print(f"    \033[31mNO DIFFERENCE — reflection not appended!\033[0m")
        return 1

    print(f"\n{RULE}")
    print(f"  {GREEN}Review the prompts above.{RESET}")
    print(f"  Does the reflection instruction help the model reason about its failure?")
    print(f"{RULE}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
